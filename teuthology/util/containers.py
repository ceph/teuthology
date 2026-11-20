import functools
import logging
import re
import requests

log = logging.getLogger(__name__)

# Our container images use a certain base image and flavor by default; those
# values are reflected below. If different values are used, they are appended
# to the image name.
DEFAULT_CONTAINER_BASE = 'centos:9'
DEFAULT_CONTAINER_FLAVOR = 'default'
DEFAULT_CONTAINER_IMAGE='quay.ceph.io/ceph-ci/ceph:{sha1}'
CONTAINER_REGEXP = re.compile(
    r"((?P<domain>[a-zA-Z0-9._-]+)/)?((?P<org>[a-zA-Z0-9_-]+)/)?((?P<image>[a-zA-Z0-9_-]+))?(:(?P<tag>[a-zA-Z0-9._-]+))?"
)


def resolve_container_image(image: str):
    """
    Given an image locator that is potentially incomplete, construct a qualified version.

    ':tag' -> 'quay.ceph.io/ceph-ci/ceph:tag'
    'image:tag' -> 'quay.ceph.io/ceph-ci/image:tag'
    'org/image:tag' -> 'quay.ceph.io/org/image:tag'
    'example.com/org/image:tag' -> 'example.com/org/image:tag'
    """
    try:
        (image_long, tag) = image.split(':')
    except ValueError:
        raise ValueError(f"Container image spec missing tag: {image}") from None
    domain = 'quay.ceph.io'
    org = 'ceph-ci'
    image = 'ceph'
    image_split = image_long.split('/')
    assert len(image_split) <= 3
    match len(image_split):
        case 3:
            (domain, org, image) = image_split
        case 2:
            (org, image) = image_split
        case _:
            if image_split[0]:
                image = image_split[0]
    return f"{domain}/{org}/{image}:{tag}"


@functools.lru_cache()
def container_image_exists(image: str):
    """
    Use the Quay API to check for the existence of a container image.
    Only tested with Quay registries.
    """
    match = re.match(CONTAINER_REGEXP, image)
    assert match
    obj = match.groupdict()
    url = f"https://{obj['domain']}/api/v1/repository/{obj['org']}/{obj['image']}/tag?filter_tag_name=eq:{obj['tag']}"
    log.info(f"Checking for container existence at: {url}")
    resp = requests.get(url)
    return resp.ok and len(resp.json().get('tags')) >= 1


def container_image_for_hash(hash: str, flavor='default', base_image='centos:9'):
    """
    Given a sha1 and optionally a base image and flavor, attempt to return a container image locator.
    """
    tag = hash
    if base_image != DEFAULT_CONTAINER_BASE:
        tag = f"{tag}-{base_image.replace(':', '-')}"
    if flavor != DEFAULT_CONTAINER_FLAVOR:
        tag = f"{tag}-{flavor}"
    image_spec = resolve_container_image(f":{tag}")
    if container_image_exists(image_spec):
        return image_spec
    else:
        log.error(f"Container image not found for hash '{hash}'")
