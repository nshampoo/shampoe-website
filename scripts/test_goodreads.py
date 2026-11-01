import csv
import io
import unittest
from datetime import date

import goodreads

EXPORT = '''Book Id,Title,Author,ISBN,ISBN13,My Rating,Date Read,Exclusive Shelf,My Review,Private Notes
1,"Dune (Dune, #1)",Frank Herbert,"=""0441013597""","=""9780441013593""",5,2026/10/12,read,Loved it,secret
2,The Way of Kings,Brandon Sanderson,"=""""","=""""",0,,currently-reading,,
3,Old Book,Someone,"=""""","=""""",3,,read,,
4,Next Up,Someone,"=""""","=""""",0,,to-read,,
5,Earlier,Someone,"=""""","=""""",4,2026/01/03,read,,
'''


class Summarize(unittest.TestCase):
    def setUp(self):
        self.out = goodreads.summarize(list(csv.DictReader(io.StringIO(EXPORT))), date(2026, 11, 1))

    def test_shelves(self):
        self.assertEqual([b["title"] for b in self.out["current"]], ["The Way of Kings"])
        self.assertEqual([b["title"] for b in self.out["recent"]], ["Dune", "Earlier"])  # no read date: left out
        self.assertEqual(self.out["total_read"], 3)
        self.assertEqual(self.out["exported"], "2026-11-01")

    def test_book_fields_and_privacy(self):
        dune = self.out["recent"][0]
        self.assertEqual(dune, {
            "title": "Dune", "author": "Frank Herbert", "rating": 5, "read": "2026-10-12",
            "cover": "https://covers.openlibrary.org/b/isbn/9780441013593-L.jpg?default=false",
            "url": "https://www.goodreads.com/book/show/1",
        })
        self.assertEqual(self.out["current"][0]["cover"], "")
        self.assertNotIn("secret", str(self.out))
        self.assertNotIn("Loved it", str(self.out))
        self.assertNotIn("Next Up", str(self.out))


if __name__ == "__main__":
    unittest.main()
