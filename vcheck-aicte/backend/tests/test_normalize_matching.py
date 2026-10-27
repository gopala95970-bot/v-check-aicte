import unittest
from datetime import date

from vcheck.matching import MATCH, MISMATCH, PROBABLE, UNAVAILABLE, compare_dates, compare_ids, compare_ints, compare_names, levenshtein
from vcheck.normalize import normalize_id, normalize_name, parse_academic_year, parse_date, parse_intake


class DateValidation(unittest.TestCase):
    def test_accepted_formats(self):
        for raw in ["15-May-2026", "15/05/2026", "15-05-2026", "2026-05-15", "May 15, 2026", "15 May 2026", "15 may 2026"]:
            with self.subTest(raw=raw):
                p = parse_date(raw)
                self.assertTrue(p.ok)
                self.assertEqual(p.value, date(2026, 5, 15))

    def test_numeric_dates_are_day_first(self):
        self.assertEqual(parse_date("03/04/2026").value, date(2026, 4, 3))

    def test_rejections_carry_a_reason(self):
        self.assertEqual(parse_date("31-02-2026").reason, "calendar_invalid")
        self.assertEqual(parse_date("29-02-2025").reason, "calendar_invalid")   # not a leap year
        self.assertEqual(parse_date("29-02-2024").value, date(2024, 2, 29))      # leap year ok
        self.assertEqual(parse_date("15/05/26").reason, "unrecognised_format")   # 2-digit years are ambiguous
        self.assertEqual(parse_date("").reason, "empty")
        self.assertEqual(parse_date(None).reason, "empty")
        self.assertEqual(parse_date("soon").reason, "unrecognised_format")


class NumberValidation(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(parse_intake("180").value, 180)
        self.assertEqual(parse_intake("1,200").value, 1200)
        self.assertEqual(parse_intake("1,20,000", max_value=10**6).value, 120000)
        self.assertEqual(parse_intake("180 (One Hundred Eighty)").value, 180)

    def test_invalid_is_rejected_not_guessed(self):
        self.assertEqual(parse_intake("1,20").reason, "not_a_number")   # malformed grouping must not become 120
        self.assertEqual(parse_intake("-5").reason, "not_a_number")
        self.assertEqual(parse_intake("0").reason, "not_positive")
        self.assertEqual(parse_intake("abc").reason, "not_a_number")
        self.assertEqual(parse_intake("99999").reason, "too_large")
        self.assertEqual(parse_intake("").reason, "empty")

    def test_academic_year(self):
        self.assertEqual(parse_academic_year("2026-27"), (2026, 2027))
        self.assertEqual(parse_academic_year("2026-2027"), (2026, 2027))
        self.assertIsNone(parse_academic_year("2026-28"))


class NameMatching(unittest.TestCase):
    def test_abbreviation_and_case_are_equal_but_labelled_normalized(self):
        r = compare_names("Sri Ram Inst. of Tech.", "SRI RAM INSTITUTE OF TECHNOLOGY")
        self.assertEqual((r.outcome, r.method), (MATCH, "normalized_equal"))

    def test_identical_is_exact(self):
        self.assertEqual(compare_names("A College", "A College").method, "exact")

    def test_spelling_variant_is_probable_never_match(self):
        self.assertEqual(compare_names("Greenfield Institute of Technology", "Greenfeld Institute of Technology").outcome, PROBABLE)

    def test_different_institution_type_is_mismatch(self):
        self.assertEqual(compare_names("Sri Ram College of Engineering", "Sri Ram College of Pharmacy").outcome, MISMATCH)

    def test_unrelated_names_mismatch(self):
        self.assertEqual(compare_names("Greenfield Institute of Technology", "Lakeside College of Pharmacy").outcome, MISMATCH)

    def test_blank_is_unavailable_not_mismatch(self):
        self.assertEqual(compare_names("", "X").outcome, UNAVAILABLE)
        self.assertEqual(compare_names("X", None).outcome, UNAVAILABLE)


class IdMatching(unittest.TestCase):
    def test_format_variation_matches(self):
        r = compare_ids("1-9000000101", "19000000101")
        self.assertEqual((r.outcome, r.method), (MATCH, "format_variation"))

    def test_ocr_confusable_is_probable(self):
        self.assertEqual(compare_ids("1-9000000101", "1-9OO0000101").outcome, PROBABLE)

    def test_single_character_difference_is_probable(self):
        self.assertEqual(compare_ids("1-9000000101", "1-9000000102").outcome, PROBABLE)

    def test_two_character_difference_is_mismatch(self):
        self.assertEqual(compare_ids("1-9000000101", "1-9000000999").outcome, MISMATCH)

    def test_levenshtein(self):
        self.assertEqual(levenshtein("kitten", "sitting"), 3)
        self.assertEqual(levenshtein("", "abc"), 3)

    def test_numbers_and_dates(self):
        self.assertEqual(compare_ints(180, 180).outcome, MATCH)
        self.assertEqual(compare_ints(180, 120).outcome, MISMATCH)
        self.assertEqual(compare_ints(None, 120).outcome, UNAVAILABLE)
        self.assertEqual(compare_dates("15-May-2026", "2026-05-15").outcome, MATCH)
        self.assertEqual(compare_dates("15-May-2026", "16-May-2026").outcome, MISMATCH)
        self.assertEqual(compare_dates("31-02-2026", "16-May-2026").outcome, UNAVAILABLE)


if __name__ == "__main__":
    unittest.main()
