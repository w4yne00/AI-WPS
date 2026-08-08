import importlib.util
import unittest


HAS_PYDANTIC = importlib.util.find_spec("pydantic") is not None

if HAS_PYDANTIC:
    from app.services.excel.formula_checks import inspect_formula


@unittest.skipUnless(HAS_PYDANTIC, "pydantic is required for formula check tests")
class ExcelFormulaChecksTests(unittest.TestCase):
    def test_basic_check_passes_without_claiming_formula_is_correct(self):
        result = inspect_formula("=SUM(B2:B10)")
        structured_reference = inspect_formula("=SUM(Table1[金额])")

        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["summary"], "基础检查通过")
        self.assertEqual(result["risks"], [])
        self.assertNotIn("正确", str(result))
        self.assertEqual(structured_reference["status"], "passed")

    def test_basic_check_reports_syntax_reference_and_compatibility_risks(self):
        cases = {
            "SUM(A1:A2)": "MISSING_EQUALS_PREFIX",
            '=IF(A1="未结束,B1,C1)': "UNBALANCED_QUOTES",
            "=SUM((A1:A2)": "UNBALANCED_PARENTHESES",
            "=" + ("A" * 8192): "FORMULA_TOO_LONG",
            "='[预算.xlsx]Sheet1'!A1": "EXTERNAL_WORKBOOK_REFERENCE",
            '=WEBSERVICE("https://example.com/data")': "NETWORK_FUNCTION_OR_URL",
            "=XFE1+XFD1048577": "OUT_OF_BOUNDS_REFERENCE",
            "=XLOOKUP(A1,B:B,C:C)": "COMPATIBILITY_REVIEW_REQUIRED",
        }

        for formula, expected_code in cases.items():
            with self.subTest(formula=formula[:40]):
                result = inspect_formula(formula)
                codes = {risk["code"] for risk in result["risks"]}
                self.assertEqual(result["status"], "risks")
                self.assertIn(expected_code, codes)
                self.assertNotIn("正确", result["summary"])

    def test_basic_check_flags_references_outside_the_explicit_selection(self):
        result = inspect_formula(
            "=SUM(B2:D3)",
            selection_address="$A$1:$C$3",
        )

        codes = {risk["code"] for risk in result["risks"]}
        self.assertIn("OUTSIDE_SELECTION_REFERENCE", codes)
        self.assertIn("D3", str(result))

    def test_basic_check_requires_review_for_functions_outside_local_support_list(self):
        unknown = inspect_formula("=FOOBAR(A1)")
        known = inspect_formula("=IF(A1>0,SUM(B1:B3),0)")

        unknown_risks = {
            risk["code"]: risk
            for risk in unknown["risks"]
        }
        self.assertIn("FUNCTION_SUPPORT_REVIEW_REQUIRED", unknown_risks)
        self.assertEqual(
            unknown_risks["FUNCTION_SUPPORT_REVIEW_REQUIRED"]["evidence"],
            "FOOBAR",
        )
        self.assertIn("未列入本地支持清单", str(unknown_risks))
        self.assertNotIn("FUNCTION_SUPPORT_REVIEW_REQUIRED", {
            risk["code"] for risk in known["risks"]
        })
        self.assertNotIn("确定不支持", str(unknown))


if __name__ == "__main__":
    unittest.main()
