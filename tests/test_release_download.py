import hashlib, io, tempfile, unittest
from pathlib import Path
import sys
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'desktop'))
from github_releases import download_asset, latest_release

class Releases(unittest.TestCase):
    def test_valid_image_and_bad_digest(self):
        data=bytearray(64);data[0]=0xe9;data[12]=9;data=bytes(data)
        asset=dict(browser_download_url='https://github.com/test/ecg/releases/download/v1/firmware.bin',size=64,digest='sha256:'+hashlib.sha256(data).hexdigest())
        with tempfile.TemporaryDirectory() as folder:
            with patch('urllib.request.urlopen',return_value=io.BytesIO(data)):
                self.assertEqual(Path(download_asset(asset,folder)).read_bytes(),data)
            asset['digest']='sha256:'+'0'*64
            with patch('urllib.request.urlopen',return_value=io.BytesIO(data)):
                with self.assertRaisesRegex(ValueError,'SHA-256'): download_asset(asset,folder)
    def test_invalid_repository(self):
        with self.assertRaises(ValueError):latest_release('https://bad.example/repo')

if __name__=='__main__':unittest.main()
