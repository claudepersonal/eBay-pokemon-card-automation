"""Upload images to eBay Picture Services via the Commerce Media API.

``createImageFromFile`` returns the new image's URI in the ``Location`` header; a
follow-up ``getImage`` yields the public EPS URL that the Inventory API accepts in
``product.imageUrls``. This keeps images hosted within eBay — no external bucket.
"""

from __future__ import annotations

from pathlib import Path

from cardlister.ebay.client import EbayClient
from cardlister.ebay.errors import EbayApiError

_CREATE_PATH = "/commerce/media/v1_beta/image/create_from_file"


def upload_image(client: EbayClient, path: Path) -> str:
    """Upload one image file and return its public EPS URL."""
    create_url = f"{client.media_base}{_CREATE_PATH}"
    with path.open("rb") as handle:
        response = client.post(
            create_url,
            files={"image": (path.name, handle, "image/jpeg")},
            expected=(201,),
        )

    location = response.headers.get("location")
    if not location:
        raise EbayApiError(response.status_code, message="createImageFromFile returned no Location")

    image = client.get(location, expected=(200,)).json()
    image_url = image.get("imageUrl") or image.get("image", {}).get("imageUrl")
    if not image_url:
        raise EbayApiError(200, message="getImage returned no imageUrl")
    return str(image_url)
