from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import translation

from tracker.models import Project


class InternationalizationTests(TestCase):
    languages = ('en', 'ar', 'zh-hans', 'es', 'fr', 'ru')

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='linguist',
            email='linguist@example.com',
            password='password123',
        )
        self.project = Project.objects.create(owner=self.user, name='Ethology', description='Project')

    def _request_for_language(self, language: str, viewname: str, args=None, authenticated: bool = False):
        client = Client()
        if authenticated:
            client.login(username='linguist', password='password123')
        with translation.override(language):
            url = reverse(viewname, args=args or [])
        response = client.get(url)
        return response, url

    def test_login_page_renders_for_all_supported_languages(self):
        for language in self.languages:
            with self.subTest(language=language):
                response, url = self._request_for_language(language, 'login')
                self.assertEqual(response.status_code, 200)
                if language == 'en':
                    self.assertEqual(url, '/accounts/login/')
                else:
                    self.assertIn(f'/{language}/', url)
                self.assertContains(response, f'lang="{language}"', html=False)

    def test_key_authenticated_pages_render_for_all_supported_languages(self):
        pages = [
            ('tracker:home', []),
            ('tracker:project_detail', [self.project.pk]),
            ('tracker:project_analytics', [self.project.pk]),
        ]
        for language in self.languages:
            for viewname, args in pages:
                with self.subTest(language=language, viewname=viewname):
                    response, url = self._request_for_language(
                        language,
                        viewname,
                        args=args,
                        authenticated=True,
                    )
                    self.assertEqual(response.status_code, 200)
                    if language == 'en':
                        self.assertFalse(url.startswith(f'/{language}/'))
                    else:
                        self.assertIn(f'/{language}/', url)
                    self.assertContains(response, f'lang="{language}"', html=False)
