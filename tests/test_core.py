"""核心口径回归测试（标准库 unittest，无需额外依赖）。

运行：.venv/bin/python -m unittest discover -s tests -v
"""
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from app.adapters import sources  # noqa: E402
from app.domain import dictionary as dic  # noqa: E402
from app.domain.normalize import build_dataset, detect_layout, inspect  # noqa: E402
from app.domain.numbers import NumberRegistry, verify  # noqa: E402
from app.domain.model import ReportDocument, ReportBlock  # noqa: E402
from app.engine.validation import has_block, validate  # noqa: E402
from app.errors import AnalysisError  # noqa: E402
from app.services import names, orchestrator  # noqa: E402
from app.services.subject import resolve  # noqa: E402
from app.storage.session import SessionStore  # noqa: E402

_SPEC = importlib.util.spec_from_file_location(
    "fetch_company_names", ROOT / "scripts" / "fetch_company_names.py")
fetch_names = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(fetch_names)


class CodeTests(unittest.TestCase):
    def test_valid_codes(self):
        self.assertEqual(resolve("600519").market, "SH")
        self.assertEqual(resolve("000001").market, "SZ")
        self.assertIn("指数", resolve("000001").note)

    def test_invalid_and_disabled(self):
        with self.assertRaises(AnalysisError):
            resolve("60051")
        with self.assertRaises(AnalysisError):
            resolve("60051A")
        with self.assertRaises(AnalysisError) as ctx:
            resolve("830001")
        self.assertEqual(ctx.exception.code, "MARKET_NOT_ENABLED")
        with self.assertRaises(AnalysisError):
            resolve("999999")


class DictionaryTests(unittest.TestCase):
    def test_aliases(self):
        self.assertEqual(dic.map_label("负债及股东权益总计")[0], "total_liab_equity")
        self.assertEqual(dic.map_label("股东权益")[0], "equity")
        self.assertEqual(dic.map_label("归属于母公司所有者的净利润")[0], "parent_net_profit")

    def test_no_concept_confusion(self):
        self.assertNotEqual(dic.map_label("营业总收入")[0], "revenue")
        self.assertNotEqual(dic.map_label("归属于母公司的净利润")[0], "net_profit")

    def test_meta_columns(self):
        self.assertEqual(dic.map_label("报告日")[2], "meta")
        self.assertEqual(dic.map_label("公告日期")[2], "meta")


class LayoutTests(unittest.TestCase):
    def test_by_date(self):
        df = pd.DataFrame({"报告日": ["20221231", "20231231"],
                           "营业收入": [100.0, 120.0], "净利润": [10.0, 12.0]})
        self.assertEqual(detect_layout(df), "by_date")

    def test_by_item(self):
        df = pd.DataFrame({"项目": ["营业收入", "净利润"],
                           "2022": [100.0, 10.0], "2023": [120.0, 12.0]})
        self.assertEqual(detect_layout(df), "by_item")

    def test_unit_scaling(self):
        df = pd.DataFrame({"项目": ["营业收入", "净利润"],
                           "2022": [100.0, 10.0], "2023": [120.0, 12.0]})
        t = inspect(df, "利润表")
        ds = build_dataset([t], origin="upload", subject="t", source_ref="t",
                           dataset_id="t", unit="万元", roles={"利润表": "IS"})
        self.assertAlmostEqual(ds.value("revenue", "2022-12-31", "IS"), 100.0 * 1e4)

    def test_non_annual_excluded(self):
        df = pd.DataFrame({"报告日": ["20221231", "20230630"],
                           "营业收入": [100.0, 60.0]})
        t = inspect(df, "利润表")
        ds = build_dataset([t], origin="upload", subject="t", source_ref="t",
                           dataset_id="t", roles={"利润表": "IS"})
        self.assertEqual(ds.periods(), ["2022-12-31"])


class ValidationTests(unittest.TestCase):
    def _dataset(self, assets: float, liab: float, equity: float):
        rows = []
        for y in (2022, 2023):
            rows.append({"报告日": f"{y}1231", "营业收入": 100.0, "营业成本": 60.0,
                         "净利润": 10.0, "资产总计": assets, "负债合计": liab,
                         "所有者权益(或股东权益)合计": equity,
                         "负债和所有者权益(或股东权益)总计": liab + equity,
                         "经营活动产生的现金流量净额": 12.0,
                         "期末现金及现金等价物余额": 5.0, "货币资金": 5.0})
        df = pd.DataFrame(rows)
        t = inspect(df, "all")
        return build_dataset([t], origin="upload", subject="t", source_ref="t",
                             dataset_id="t", roles={"all": "BS"})

    def test_balance_mismatch_blocked(self):
        ds = self._dataset(100.0, 40.0, 50.0)   # 负债+权益 = 90，不等于资产 100
        self.assertTrue(has_block(validate(ds)))

    def test_all_three_statements_required(self):
        ds = self._dataset(100.0, 40.0, 60.0)
        self.assertTrue(any(i.code == "MISSING_STATEMENT" for i in validate(ds)))


class NumberConsistencyTests(unittest.TestCase):
    def test_detects_unregistered_number(self):
        reg = NumberRegistry()
        reg.amount(12.345)
        doc = ReportDocument("t", "t", [ReportBlock("paragraph", "营收 12.35 亿元，另有 99.99 亿元。")],
                             {}, "")
        ok, unknown = verify(doc, reg)
        self.assertFalse(ok)
        self.assertEqual(unknown, ["99.99"])

    def test_structural_numbers_ignored(self):
        reg = NumberRegistry()
        doc = ReportDocument("t", "t", [ReportBlock("paragraph", "2024 年第 3 章，共 14 张图。")],
                             {}, "")
        ok, unknown = verify(doc, reg)
        self.assertTrue(ok)
        self.assertEqual(unknown, [])

    def test_all_registered_passes(self):
        reg = NumberRegistry()
        text = f"毛利率 {reg.pct(0.153)}，营收 {reg.amount(1234.5)}，同比 {reg.pp(0.02)}。"
        doc = ReportDocument("t", "t", [ReportBlock("paragraph", text)], {}, "")
        ok, unknown = verify(doc, reg)
        self.assertTrue(ok, unknown)


class CompanyNameTests(unittest.TestCase):
    def test_local_snapshot_hit(self):
        info = names.describe("600519")
        self.assertEqual(info["company_name"], "贵州茅台")
        self.assertEqual(info["display_name"], "贵州茅台（600519）")
        self.assertIn("本地证券简称表", info["name_source"])

    def test_normalize_name(self):
        self.assertEqual(names.normalize_name("万  科Ａ"), "万科A")
        self.assertEqual(names.normalize_name("五 粮 液"), "五粮液")
        self.assertEqual(names.normalize_name("*ST 某某 1.2"), "*ST某某12")

    def test_miss_and_invalid_code(self):
        self.assertIsNone(names.lookup("abc"))
        miss = names.describe("999999")
        self.assertIsNone(miss["company_name"])
        self.assertEqual(miss["display_name"], "999999")

    def test_resolver_registry_extension(self):
        class Only:
            name = "test-only"

            def resolve(self, code):
                return ("测试公司", "单元测试解析器") if code == "888888" else None

        resolver = Only()
        names.register_name_resolver(resolver, first=True)
        try:
            self.assertEqual(names.lookup("888888").name, "测试公司")
            self.assertEqual(names.lookup("888888").source, "单元测试解析器")
        finally:
            names.RESOLVERS.remove(resolver)
        self.assertIsNone(names.lookup("888888"))


class NameRefreshTests(unittest.TestCase):
    """快照刷新场景：新增编码、公司更名、损坏自愈、原子写入。"""

    @staticmethod
    def _payload(names: dict[str, str], as_of: str = "2026-11-19") -> dict:
        return {
            "as_of": as_of,
            "source": "unit test",
            "count": len(names),
            "names": dict(sorted(names.items())),
        }

    def test_reload_without_restart(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "company_names.json"
            path.write_text(json.dumps(self._payload({"600519": "贵州茅台"})), encoding="utf-8")
            resolver = names.LocalNameResolver(path=path)
            self.assertEqual(resolver.resolve("600519")[0], "贵州茅台")
            self.assertIsNone(resolver.resolve("301999"))   # 新股尚未上市

            # 服务进程不重启，仅刷新快照：新增编码 + 公司更名
            updated = self._payload({"600519": "贵州茅台酒", "301999": "新股股份"},
                                    "2026-11-20")
            fetch_names.write_atomic(updated, path)
            self.assertEqual(resolver.resolve("600519")[0], "贵州茅台酒")
            self.assertEqual(resolver.resolve("301999")[0], "新股股份")
            self.assertIn("2026-11-20", resolver.resolve("600519")[1])

    def test_corrupt_snapshot_self_heals(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "company_names.json"
            path.write_text('{"names": {', encoding="utf-8")   # 半截 JSON
            resolver = names.LocalNameResolver(path=path)
            self.assertIsNone(resolver.resolve("600519"))
            path.write_text(json.dumps(self._payload({"600519": "贵州茅台"})), encoding="utf-8")
            self.assertEqual(resolver.resolve("600519")[0], "贵州茅台")

    def test_atomic_write_leaves_no_tmp(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "company_names.json"
            fetch_names.write_atomic(self._payload({"600519": "贵州茅台"}), path)
            self.assertTrue(path.exists())
            self.assertFalse((Path(d) / "company_names.json.tmp").exists())
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["count"], 1)

    def test_diff_names_added_changed_removed(self):
        old = {"600519": "贵州茅台", "000001": "平安银行", "000002": "旧名字"}
        new = {"600519": "贵州茅台酒", "000001": "平安银行", "301999": "新股股份"}
        changes = fetch_names.diff_names(old, new)
        self.assertEqual(changes["added"], ["301999"])
        self.assertEqual(changes["changed"], ["600519"])
        self.assertEqual(changes["removed"], ["000002"])

    def test_manual_set_and_delete(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "company_names.json"
            fetch_names.write_atomic(self._payload({"600519": "贵州茅台"}), path)
            fetch_names.apply_manual([("301999", "新股股份"), ("600519", "贵州新名")],
                                     [], path)
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["names"]["301999"], "新股股份")
            self.assertEqual(data["names"]["600519"], "贵州新名")
            self.assertEqual(data["count"], 2)
            fetch_names.apply_manual([], ["301999"], path)
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotIn("301999", data["names"])
            self.assertEqual(data["names"]["600519"], "贵州新名")

    def test_manual_rejects_invalid_code(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "company_names.json"
            fetch_names.write_atomic(self._payload({"600519": "贵州茅台"}), path)
            with self.assertRaises(ValueError):
                fetch_names.apply_manual([("ABC", "无效")], [], path)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["count"], 1)

    def test_online_failure_keeps_snapshot(self):
        from unittest import mock

        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "company_names.json"
            fetch_names.write_atomic(self._payload({"600519": "贵州茅台"}), path)

            class BrokenSource:
                @staticmethod
                def stock_info_a_code_name():
                    raise OSError("proxy down")

            with mock.patch.dict(sys.modules, {"akshare": BrokenSource}):
                with self.assertRaises(RuntimeError) as ctx:
                    fetch_names.refresh_online(path)
            self.assertIn("手动维护", str(ctx.exception))
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["names"]["600519"], "贵州茅台")
            self.assertFalse(Path(str(path) + ".tmp").exists())


class UnknownCodeTests(unittest.TestCase):
    """本地快照未收录代码：明确错误码与可操作数据。"""

    def test_local_statement_probe(self):
        self.assertTrue(sources.has_local_statements("600519"))
        self.assertFalse(sources.has_local_statements("600520"))
        self.assertFalse(sources.has_local_statements("000858"))

    def test_mock_source_raises_typed_miss(self):
        with self.assertRaises(sources.LocalSnapshotMiss) as ctx:
            sources.MockFileSource().fetch("600520")
        self.assertEqual(ctx.exception.code, "600520")
        self.assertEqual(len(ctx.exception.missing), 3)
        self.assertIn("600520_income.csv", ctx.exception.missing)

    def test_orchestrator_emits_structured_error(self):
        with self.assertRaises(AnalysisError) as ctx:
            orchestrator.dataset_from_code("600520", "mock")
        err = ctx.exception
        self.assertEqual(err.code, "LOCAL_SNAPSHOT_MISS")
        self.assertIn("600520", err.message)
        self.assertEqual(err.data["code"], "600520")
        self.assertEqual(len(err.data["missing_files"]), 3)
        self.assertEqual(err.data["actions"],
                         ["switch_online_source", "upload_statements"])

    def test_covered_code_still_loads(self):
        dataset, subject, _ = orchestrator.dataset_from_code("600519", "mock")
        self.assertEqual(dataset.subject, "贵州茅台（600519）")
        self.assertEqual(subject.market, "SH")


class OnlineCodeNotFoundTests(unittest.TestCase):
    """在线源查无此股：把晦涩 TypeError 转成可操作的结构化错误。"""

    def test_describe_flags_name_table_membership(self):
        self.assertFalse(names.describe("688999")["in_name_table"])
        self.assertTrue(names.describe("600519")["in_name_table"])

    def test_akshare_none_type_becomes_typed_error(self):
        from unittest import mock

        class BrokenAk:
            @staticmethod
            def stock_financial_report_sina(symbol, indicator):
                raise TypeError("'NoneType' object is not subscriptable")

        with mock.patch.dict(sys.modules, {"akshare": BrokenAk}):
            with self.assertRaises(sources.OnlineCodeNotFound) as ctx:
                sources.AkShareSource().fetch("688999")
        err = ctx.exception
        self.assertEqual(err.code, "688999")
        self.assertFalse(err.in_name_table)
        self.assertIsInstance(err.cause, TypeError)

    def test_other_akshare_errors_stay_untouched(self):
        from unittest import mock

        class TimeoutAk:
            @staticmethod
            def stock_financial_report_sina(symbol, indicator):
                raise OSError("read timeout")

        with mock.patch.dict(sys.modules, {"akshare": TimeoutAk}):
            with self.assertRaises(OSError):
                sources.AkShareSource().fetch("688999")

    def test_orchestrator_maps_to_structured_error(self):
        from unittest import mock

        cause = sources.OnlineCodeNotFound("688999", TypeError("NoneType"), False)
        with mock.patch.object(sources.AkShareSource, "fetch", side_effect=cause):
            with self.assertRaises(AnalysisError) as ctx:
                orchestrator.dataset_from_code("688999", "akshare")
        err = ctx.exception
        self.assertEqual(err.code, "ONLINE_CODE_NOT_FOUND")
        self.assertIn("688999", err.message)
        # 原因必须同时点明「简称表未收录」与「在线接口也未返回」两个证据，
        # 不能仅凭简称表缺失就断言代码无效（新股常是简称表缺、在线有数据）
        self.assertIn("在线接口也未返回", err.data["reason"])
        self.assertIn("刷新简称表", err.data["reason"])
        self.assertEqual(err.data["code"], "688999")
        self.assertIsNone(err.data["known_name"])
        self.assertEqual(err.data["actions"], ["check_code", "upload_statements"])

    def test_name_table_miss_but_online_has_data(self):
        """简称表缺失 ≠ 无数据：新股换在线源能取到财报时，分析照常完成、名称降级为代码。"""
        from unittest import mock

        # 市场规则支持 688981，但简称表（临时快照）未收录它
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "company_names.json"
            fetch_names.write_atomic(
                {"as_of": "2026-11-19", "source": "test", "count": 1,
                 "names": {"600519": "贵州茅台"}}, path)
            resolver = names.LocalNameResolver(path=path)
            with mock.patch.object(names.RESOLVERS[0], "resolve", side_effect=resolver.resolve):
                self.assertIsNone(names.lookup("688981"))
                self.assertFalse(names.describe("688981")["in_name_table"])
                # 模拟在线源返回三张合法报表（用本地 demo 三表充当结构完整的返回）
                demo = {}
                for st, fn in (("IS", "income_statement.csv"),
                               ("BS", "balance_sheet.csv"), ("CF", "cash_flow.csv")):
                    demo[st] = pd.read_csv(ROOT / "data/demo" / fn, dtype={"报告日": str})
                with mock.patch.object(sources.AkShareSource, "fetch", return_value=demo):
                    dataset, subject, _ = orchestrator.dataset_from_code("688981", "akshare")
                self.assertEqual(dataset.subject, "688981")   # 名称降级为 6 位代码
                self.assertEqual(dataset.company_name, "")
                self.assertEqual(subject.market, "SH")

    def test_in_table_but_no_data_reason(self):
        from unittest import mock

        cause = sources.OnlineCodeNotFound("600520", TypeError("NoneType"), True)
        with mock.patch.object(sources.AkShareSource, "fetch", side_effect=cause):
            with self.assertRaises(AnalysisError) as ctx:
                orchestrator.dataset_from_code("600520", "akshare")
        self.assertIn("已退市或接口数据缺失", ctx.exception.data["reason"])
        self.assertEqual(ctx.exception.data["known_name"], "三佳科技")


class NameBackfillTests(unittest.TestCase):
    """在线取数成功后简称表自动补录：只增不覆盖、原子写、失败静默、按需触发。"""

    @staticmethod
    def _payload(names: dict[str, str], **extra) -> dict:
        payload = {"as_of": "2026-11-19", "source": "test", "count": len(names),
                   "names": dict(sorted(names.items()))}
        payload.update(extra)
        return payload

    def test_adds_missing_code_with_annotation(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "company_names.json"
            fetch_names.write_atomic(self._payload({"600519": "贵州茅台"}), path)
            result = names.backfill_name(
                "688001", name_lookup=lambda c: "华兴源创", path=path)
            self.assertTrue(result.added)
            self.assertEqual(result.name, "华兴源创")
            self.assertEqual(result.reason, "added")
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["names"]["688001"], "华兴源创")
            self.assertEqual(data["count"], 2)
            self.assertIn("688001", data["backfilled"])
            # 来源文案带补录标注，供报告与界面审计
            resolver = names.LocalNameResolver(path=path)
            self.assertIn("在线补录", resolver.resolve("688001")[1])

    def test_existing_code_not_overwritten(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "company_names.json"
            fetch_names.write_atomic(self._payload({"688001": "华兴源创（手动更正）"}), path)
            result = names.backfill_name(
                "688001", name_lookup=lambda c: "在线旧名", path=path)
            self.assertFalse(result.added)
            self.assertEqual(result.reason, "already_present")
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["names"]["688001"], "华兴源创（手动更正）")

    def test_lookup_failure_silent_no_write(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "company_names.json"
            fetch_names.write_atomic(self._payload({"600519": "贵州茅台"}), path)
            result = names.backfill_name("688999", name_lookup=lambda c: None, path=path)
            self.assertFalse(result.added)
            self.assertEqual(result.reason, "lookup_failed")
            self.assertNotIn("688999", json.loads(path.read_text(encoding="utf-8"))["names"])

    def test_lookup_exception_silent(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "company_names.json"
            fetch_names.write_atomic(self._payload({"600519": "贵州茅台"}), path)

            def boom(code):
                raise OSError("proxy down")

            result = names.backfill_name("688001", name_lookup=boom, path=path)
            self.assertFalse(result.added)
            self.assertEqual(result.reason, "write_failed")

    def test_invalid_code_rejected(self):
        result = names.backfill_name("ABC", name_lookup=lambda c: "某", path=Path("/nonexistent"))
        self.assertFalse(result.added)
        self.assertEqual(result.reason, "invalid_code")

    def test_atomic_write_leaves_no_tmp(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "company_names.json"
            fetch_names.write_atomic(self._payload({"600519": "贵州茅台"}), path)
            names.backfill_name("688001", name_lookup=lambda c: "华兴源创", path=path)
            self.assertFalse((Path(d) / "company_names.json.tmp").exists())

    def test_disabled_by_config(self):
        from unittest import mock

        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "company_names.json"
            fetch_names.write_atomic(self._payload({"600519": "贵州茅台"}), path)
            with mock.patch.object(names.config, "NAME_BACKFILL_ONLINE", 0):
                result = names.backfill_name(
                    "688001", name_lookup=lambda c: "华兴源创", path=path)
            self.assertFalse(result.added)
            self.assertNotIn("688001", json.loads(path.read_text(encoding="utf-8"))["names"])

    def test_only_online_source_triggers_backfill(self):
        """编排层：mock 离线源取数即使简称表缺名，也不得触发在线补录。"""
        from unittest import mock

        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "company_names.json"
            fetch_names.write_atomic(self._payload({"600519": "贵州茅台"}), path)
            with mock.patch.object(names.config, "COMPANY_NAMES_PATH", path):
                with mock.patch.object(names, "backfill_name",
                                       wraps=names.backfill_name) as spy:
                    # 600519 在 mock 源有财报；用临时表让它缺名，验证不触发补录
                    with mock.patch.object(names.RESOLVERS[0], "resolve",
                                           side_effect=names.LocalNameResolver(path=path).resolve):
                        demo = pd.read_csv(ROOT / "data/raw/600519_income.csv", dtype={"报告日": str})
                        with mock.patch.object(sources.MockFileSource, "fetch",
                                               return_value={"IS": demo, "BS": demo, "CF": demo}):
                            orchestrator.dataset_from_code("600519", "mock")
            spy.assert_not_called()

    def test_online_source_triggers_backfill_and_uses_new_name(self):
        """编排层：在线源取数成功且简称表缺名时触发补录，本次即用上新名称。"""
        from unittest import mock

        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "company_names.json"
            fetch_names.write_atomic(self._payload({"600519": "贵州茅台"}), path)
            local = names.LocalNameResolver(path=path)
            demo = {}
            for st, fn in (("IS", "income_statement.csv"),
                           ("BS", "balance_sheet.csv"), ("CF", "cash_flow.csv")):
                demo[st] = pd.read_csv(ROOT / "data/demo" / fn, dtype={"报告日": str})
            with mock.patch.object(names.config, "COMPANY_NAMES_PATH", path):
                with mock.patch.object(names.RESOLVERS[0], "resolve", side_effect=local.resolve):
                    with mock.patch.object(names, "fetch_online_name", return_value="华兴源创"):
                        with mock.patch.object(sources.AkShareSource, "fetch", return_value=demo):
                            dataset, _, _ = orchestrator.dataset_from_code("688001", "akshare")
            self.assertEqual(dataset.company_name, "华兴源创")
            self.assertIn("在线补录", dataset.name_source)
            self.assertEqual(dataset.name_backfill["reason"], "added")
            self.assertTrue(dataset.name_backfill["added"])


class SessionTests(unittest.TestCase):
    def test_destroy_removes_directory(self):
        with tempfile.TemporaryDirectory() as d:
            store = SessionStore(root=Path(d), ttl=3600, sweep=60)
            s = store.create()
            f = s.root / "raw.csv"
            f.write_text("x", encoding="utf-8")
            self.assertTrue(f.exists())
            store.destroy(s.id)
            self.assertFalse(s.root.exists())
            self.assertIsNone(store.get(s.id))

    def test_expiry(self):
        with tempfile.TemporaryDirectory() as d:
            store = SessionStore(root=Path(d), ttl=-1, sweep=60)
            s = store.create()
            self.assertIsNone(store.get(s.id))
            self.assertFalse(s.root.exists())

    def test_resolve_rejects_unknown_key(self):
        with tempfile.TemporaryDirectory() as d:
            store = SessionStore(root=Path(d), ttl=3600, sweep=60)
            s = store.create()
            self.assertIsNone(store.resolve(s.id, "../../etc/passwd"))


if __name__ == "__main__":
    unittest.main()
