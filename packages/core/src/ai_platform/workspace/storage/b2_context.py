from dataclasses import dataclass
from b2sdk.v2 import B2Api, InMemoryAccountInfo
from b2sdk.v2.bucket import Bucket

@dataclass(frozen=True)
class B2Context:
    b2_api: B2Api
    bucket: Bucket

def make_b2_context(*, application_key_id: str, application_key: str, bucket_name: str) -> B2Context:
    info = InMemoryAccountInfo()
    b2_api = B2Api(info)
    b2_api.authorize_account("production", application_key_id, application_key)
    bucket = b2_api.get_bucket_by_name(bucket_name)
    return B2Context(b2_api=b2_api, bucket=bucket)
