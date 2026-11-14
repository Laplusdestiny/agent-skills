import unittest

from shop.discount import apply_discount


class DiscountTest(unittest.TestCase):
    def test_ten_percent(self):
        self.assertEqual(apply_discount(100.0, 10), 90.0)


if __name__ == "__main__":
    unittest.main()
