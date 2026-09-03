"""Tests for section hierarchy helpers used by the syllabus sidebar."""
from django.test import SimpleTestCase

from myApp.utils.lesson_hierarchy import (
    clean_lesson_nav_title,
    lesson_nest_depth,
    parse_section_parts,
    section_sort_key,
    sort_lessons_by_section,
)


class LessonHierarchyTests(SimpleTestCase):
    def test_parse_and_depth(self):
        self.assertEqual(parse_section_parts("2.4 ENTRY"), (2, 4))
        self.assertEqual(parse_section_parts("2.4.1 STEP ENTRY"), (2, 4, 1))
        self.assertEqual(lesson_nest_depth("Introduction"), 0)
        self.assertEqual(lesson_nest_depth("2.4 ENTRY"), 1)
        self.assertEqual(lesson_nest_depth("2.4.2 RAMP ENTRY"), 2)

    def test_clean_chapter_echo_title(self):
        self.assertEqual(
            clean_lesson_nav_title("2.4.2 RAMP ENTRY CHAPTER 2.4.2 RAMP ENTRY"),
            "2.4.2 RAMP ENTRY",
        )
        self.assertEqual(
            clean_lesson_nav_title("2.2.2 PRECAUTIONS CHAPTER 2.2.2 PRECAUTIONS"),
            "2.2.2 PRECAUTIONS",
        )

    def test_sort_puts_parent_before_children(self):
        class L:
            def __init__(self, title, order, id):
                self.title = title
                self.order = order
                self.id = id

        messy = [
            L("2.4.1 STEP ENTRY TECHNIQUE", 1, 1),
            L("2.4.2 RAMP ENTRY", 2, 2),
            L("2.4 ENTRY & EXIT PROCEDURES", 3, 3),
            L("2.4.3 LIFT ENTRY", 4, 4),
            L("2.3 ENVIRONMENTAL SAFETY", 5, 5),
            L("2.3.1 POOL CHEMISTRY", 6, 6),
        ]
        titles = [l.title for l in sort_lessons_by_section(messy)]
        self.assertEqual(
            titles,
            [
                "2.3 ENVIRONMENTAL SAFETY",
                "2.3.1 POOL CHEMISTRY",
                "2.4 ENTRY & EXIT PROCEDURES",
                "2.4.1 STEP ENTRY TECHNIQUE",
                "2.4.2 RAMP ENTRY",
                "2.4.3 LIFT ENTRY",
            ],
        )

    def test_section_sort_key_padding(self):
        self.assertLess(
            section_sort_key("2.3 FOO"),
            section_sort_key("2.3.1 BAR"),
        )
