import unittest

from shop.pagination import paginate


class PaginateTest(unittest.TestCase):
    def test_first_page(self):
        self.assertEqual(paginate(list(range(25)), 1), list(range(10)))

    def test_last_partial_page(self):
        self.assertEqual(paginate(list(range(25)), 3), list(range(20, 25)))

    def test_rejects_page_zero(self):
        with self.assertRaises(ValueError):
            paginate([1, 2, 3], 0)


if __name__ == "__main__":
    unittest.main()
