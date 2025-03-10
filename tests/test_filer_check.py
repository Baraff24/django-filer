import os
import shutil
from io import BytesIO, StringIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase
from django.utils.module_loading import import_string

from filer import settings as filer_settings
from filer.models.filemodels import File
from filer.settings import FILER_IMAGE_MODEL
from filer.utils.loader import load_model
from tests.helpers import create_image

Image = load_model(FILER_IMAGE_MODEL)


class FilerCheckTestCase(TestCase):
    svg_file_string = """<?xml version="1.0" encoding="UTF-8" standalone="no"?>
    <!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "
    http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">
    <svg version="1.1" baseProfile="full" width="50" height="50" xmlns="http://www.w3.org/2000/svg">
       <polygon id="triangle" points="0,0 0,50 50,0" fill="#009900"
    stroke="#004400"/>
       {}
    </svg>"""

    def setUp(self):
        # Clean up the public folder to avoid interference between tests.
        public_settings = filer_settings.FILER_STORAGES['public']['main']
        storage = import_string(public_settings['ENGINE'])()
        upload_prefix = public_settings['UPLOAD_TO_PREFIX']
        if storage.exists(upload_prefix):
            shutil.rmtree(storage.path(upload_prefix))

        original_filename = 'testimage.jpg'
        file_obj = SimpleUploadedFile(
            name=original_filename,
            content=create_image().tobytes(),
            content_type='image/jpeg'
        )
        self.filer_file = File.objects.create(
            file=file_obj,
            original_filename=original_filename
        )

    def tearDown(self):
        self.filer_file.delete()

    def test_delete_missing(self):
        out = StringIO()
        self.assertTrue(os.path.exists(self.filer_file.file.path))
        file_pk = self.filer_file.id
        call_command('filer_check', stdout=out, missing=True)
        self.assertEqual('', out.getvalue())

        os.remove(self.filer_file.file.path)
        call_command('filer_check', stdout=out, missing=True)
        self.assertEqual("None/testimage.jpg\n", out.getvalue())
        self.assertIsInstance(File.objects.get(id=file_pk), File)

        call_command('filer_check', delete_missing=True, interactive=False, verbosity=0)
        with self.assertRaises(File.DoesNotExist):
            File.objects.get(id=file_pk)

    def test_delete_orphans_public(self):
        out = StringIO()
        self.assertTrue(os.path.exists(self.filer_file.file.path))
        call_command('filer_check', stdout=out, orphans=True)
        # The public folder should be free of orphaned files.
        self.assertEqual('', out.getvalue())

        # Add an orphan file to the public storage.
        public_settings = filer_settings.FILER_STORAGES['public']['main']
        storage = import_string(public_settings['ENGINE'])()
        public_path = storage.path(public_settings['UPLOAD_TO_PREFIX'])
        orphan_file = os.path.join(public_path, 'hello.txt')
        os.makedirs(public_path, exist_ok=True)
        with open(orphan_file, 'w') as fh:
            fh.write("I don't belong here!")
        call_command('filer_check', stdout=out, orphans=True)
        self.assertEqual("public/hello.txt\n", out.getvalue())
        self.assertTrue(os.path.exists(orphan_file))

        call_command('filer_check', delete_orphans=True, interactive=False, verbosity=0)
        self.assertFalse(os.path.exists(orphan_file))

    def test_delete_orphans_private(self):
        # Skip test if private storage is not configured.
        if 'private' not in filer_settings.FILER_STORAGES:
            self.skipTest("Private storage not configured in FILER_STORAGES.")

        out = StringIO()
        private_settings = filer_settings.FILER_STORAGES['private']['main']
        storage = import_string(private_settings['ENGINE'])()
        if private_settings.get('OPTIONS', {}).get('location'):
            storage.location = private_settings['OPTIONS']['location']
        private_path = storage.path(private_settings['UPLOAD_TO_PREFIX'])
        os.makedirs(private_path, exist_ok=True)

        orphan_file = os.path.join(private_path, 'private_orphan.txt')
        with open(orphan_file, 'w') as fh:
            fh.write("I don't belong here!")
        # Verify that the command detects the orphan file.
        call_command('filer_check', stdout=out, orphans=True)
        self.assertIn("private_orphan.txt", out.getvalue())
        self.assertTrue(os.path.exists(orphan_file))

        # Delete the orphan file.
        call_command('filer_check', delete_orphans=True, interactive=False, verbosity=0)
        self.assertFalse(os.path.exists(orphan_file))

    def test_image_dimensions_corrupted_file(self):
        original_filename = 'testimage.jpg'
        file_obj = SimpleUploadedFile(
            name=original_filename,
            content=create_image().tobytes(),  # corrupted file
            content_type='image/jpeg'
        )
        self.filer_image = Image.objects.create(
            file=file_obj,
            original_filename=original_filename
        )
        self.filer_image._width = 0
        self.filer_image.save()
        call_command('filer_check', image_dimensions=True)

    def test_image_dimensions_file_not_found(self):
        self.filer_image = Image.objects.create(
            file="123.jpg",
            original_filename="123.jpg"
        )
        call_command('filer_check', image_dimensions=True)
        self.filer_image.refresh_from_db()

    def test_image_dimensions(self):
        original_filename = 'testimage.jpg'
        with BytesIO() as jpg:
            create_image().save(jpg, format='JPEG')
            jpg.seek(0)
            file_obj = SimpleUploadedFile(
                name=original_filename,
                content=jpg.read(),
                content_type='image/jpeg'
            )
            self.filer_image = Image.objects.create(
                file=file_obj,
                original_filename=original_filename
            )
        self.filer_image._width = 0
        self.filer_image.save()

        call_command('filer_check', image_dimensions=True)
        self.filer_image.refresh_from_db()
        self.assertGreater(self.filer_image._width, 0)

    def test_image_dimensions_invalid_svg(self):
        original_filename = 'test.svg'
        svg_file = bytes("<asdva>" + self.svg_file_string, "utf-8")
        file_obj = SimpleUploadedFile(
            name=original_filename,
            content=svg_file,
            content_type='image/svg+xml'
        )
        self.filer_image = Image.objects.create(
            file=file_obj,
            original_filename=original_filename
        )
        self.filer_image._width = 0
        self.filer_image.save()
        call_command('filer_check', image_dimensions=True)

    def test_image_dimensions_svg(self):
        original_filename = 'test.svg'
        svg_file = bytes(self.svg_file_string, "utf-8")
        file_obj = SimpleUploadedFile(
            name=original_filename,
            content=svg_file,
            content_type='image/svg+xml'
        )
        self.filer_image = Image.objects.create(
            file=file_obj,
            original_filename=original_filename
        )
        self.filer_image._width = 0
        self.filer_image.save()

        call_command('filer_check', image_dimensions=True)
        self.filer_image.refresh_from_db()
        self.assertGreater(self.filer_image._width, 0)
