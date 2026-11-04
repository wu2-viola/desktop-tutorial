"""demo 工作区的测试：当前 mean 的空列表行为会导致 1 个用例失败。"""
import unittest

from stats import mean, median, variance


class StatsTest(unittest.TestCase):
    def test_mean_basic(self):
        self.assertEqual(mean([1, 2, 3]), 2.0)

    def test_mean_floats(self):
        self.assertAlmostEqual(mean([1.5, 2.5]), 2.0)

    def test_mean_negative(self):
        self.assertEqual(mean([-1, -2, -3]), -2.0)

    def test_mean_empty_raises(self):
        with self.assertRaises(ValueError):
            mean([])

    def test_variance(self):
        self.assertAlmostEqual(variance([2, 4, 6]), 8.0 / 3.0)

    def test_median(self):
        self.assertEqual(median([3, 1, 2]), 2)
        self.assertEqual(median([4, 1, 3, 2]), 2.5)


if __name__ == "__main__":
    unittest.main()
