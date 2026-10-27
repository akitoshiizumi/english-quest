import io
import json
import unittest
import urllib.error

from english_overlap.openai_api import OpenAIError, request_json, response_text


class FakeResponse:
    def __init__(self, data): self.data=data
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def read(self): return json.dumps(self.data).encode()


class OpenAIBoundaryTests(unittest.TestCase):
    def test_transport_is_injectable_and_key_stays_in_server_request(self):
        captured=[]
        def transport(request, timeout):
            captured.append((request.full_url,request.get_header('Authorization'),timeout))
            return FakeResponse({'output_text':'fixture'})
        result=request_json('responses',{'model':'fixture','input':'test'},api_key='fixture-secret',transport=transport)
        self.assertEqual(response_text(result),'fixture')
        self.assertEqual(captured[0][0],'https://api.openai.com/v1/responses')
        self.assertEqual(captured[0][1],'Bearer fixture-secret')
        self.assertEqual(captured[0][2],90)

    def test_missing_key_and_http_errors_are_safe_and_classified(self):
        with self.assertRaises(OpenAIError): request_json('responses',{},api_key='')
        def rate_limited(*args,**kwargs): raise urllib.error.HTTPError('url',429,'rate',{},io.BytesIO(b'secret response'))
        with self.assertRaises(OpenAIError) as error: request_json('embeddings',{},api_key='secret',transport=rate_limited)
        self.assertTrue(error.exception.retryable)
        self.assertNotIn('secret',str(error.exception))


if __name__ == '__main__': unittest.main()
