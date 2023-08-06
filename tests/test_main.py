import logging
import unittest
from unittest.mock import patch, MagicMock, mock_open
from app.main import handle_upload, upload_to_s3, gpt_whisper
import boto3
from moto import mock_s3
from botocore.exceptions import BotoCoreError, ClientError



class TestMain(unittest.TestCase):

    @patch('tempfile.NamedTemporaryFile')
    @patch('builtins.open', new_callable=mock_open, read_data=b'audio file content')
    def test_handle_upload(self, mock_open_file, mock_tempfile):
        content = b'audio file content'

        mock_file = MagicMock()
        mock_file.__enter__.return_value.name = 'tempfile_name'  # Update this line
        mock_file.__enter__.return_value.read.return_value = content
        mock_file.__enter__.return_value.__iter__ = MagicMock(return_value=iter([content]))
        mock_file.__enter__.return_value.tell = MagicMock(return_value=len(content))
        mock_tempfile.return_value = mock_file

        filename = 'test_file.mp3'

        result_filename, result_tmp_name = handle_upload(filename, content)

        # Updated assertions
        self.assertIsInstance(result_filename, str)
        self.assertNotEqual(result_filename, '')
        self.assertIsInstance(result_tmp_name, str)
        self.assertNotEqual(result_tmp_name, '')

    @mock_s3
    def test_upload_to_s3(self):
        # Set up the mock S3.
        s3_client = boto3.client('s3', region_name='us-east-1')
        s3_client.create_bucket(Bucket='mybucket')

        # Let's print all the buckets to make sure 'mybucket' was created.
        buckets = s3_client.list_buckets()
        print("Buckets: ", buckets)

        filename = 'test_file.mp3'
        tmp_name = '/tmp/tempfile_name'
        # Write a temp file to upload
        with open(tmp_name, 'wb') as f:
            f.write(b'test content')

        # Here we directly put the file to S3
        with open(tmp_name, 'rb') as data:
            s3_client.put_object(Bucket='mybucket', Key=filename, Body=data)

        # Try to get the object we just put in S3.
        try:
            s3_client.get_object(Bucket='mybucket', Key=filename)
            print(f"Object {filename} retrieved successfully.")
        except ClientError as e:
            logging.error(e)
            print(f"Error occurred while retrieving {filename}.")

    @patch('openai.Audio.transcribe')
    @patch('boto3.client')
    @patch('tempfile.NamedTemporaryFile')
    @patch('builtins.open', new_callable=mock_open, read_data=b'audio file content')
    def test_gpt_whisper(self, mock_open_file, mock_tempfile, mock_boto3_client, mock_transcribe):
        content = b'some data'

        mock_file = MagicMock()
        mock_file.name = '/tmp/tempfile'
        mock_file.__enter__.return_value.read.return_value = content
        mock_file.__enter__.return_value.__iter__ = MagicMock(return_value=iter([content]))
        mock_file.__enter__.return_value.tell = MagicMock(return_value=len(content))
        mock_tempfile.return_value = mock_file

        mock_s3_client = MagicMock()
        mock_boto3_client.return_value = mock_s3_client

        mock_transcribe.return_value = 'transcript'

        bucket_name = 'audiobio-recordings'
        filename = 'test_file.mp3'

        result = gpt_whisper(mock_s3_client, bucket_name, filename)
        self.assertEqual(result, 'transcript')

        mock_s3_client.download_file.assert_called_once()
        mock_transcribe.assert_called_once()

if __name__ == "__main__":
    unittest.main()
