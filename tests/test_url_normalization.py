import unittest

from utils.article_urls import normalize_article_url


class UrlNormalizationTests(unittest.TestCase):
    def test_removes_only_utm_parameters(self):
        url = 'https://press.example/view?idxno=123&utm_source=naver&empty=&UTM_campaign=test#section'
        self.assertEqual(normalize_article_url(url), 'https://press.example/view?idxno=123&empty=#section')

    def test_article_identifier_and_query_values_are_preserved(self):
        self.assertEqual(normalize_article_url('https://press.example/view?key=123&value=a%26b'),
                         'https://press.example/view?key=123&value=a%26b')
