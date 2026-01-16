import pytest

from unittest.mock import patch

from teuthology.util import containers

@pytest.mark.parametrize(
    'input, expected',
    [
        (':hash', 'quay.ceph.io/ceph-ci/ceph:hash'),
        ('image:hash', 'quay.ceph.io/ceph-ci/image:hash'),
        ('org/image:hash', 'quay.ceph.io/org/image:hash'),
        ('example.com/org/image:hash', 'example.com/org/image:hash'),
        ('image', ValueError),
        ('org/image', ValueError),
        ('domain.net/org/image', ValueError),
    ]
)
def test_resolve_container_image(input, expected):
    if isinstance(expected, str):
        assert expected == containers.resolve_container_image(input)
    else:
        with pytest.raises(expected):
            containers.resolve_container_image(input)

@pytest.mark.parametrize(
    'image, url',
    [
        ('example.com/org/image:tag', 'https://example.com/api/v1/repository/org/image/tag?filter_tag_name=eq:tag'),
    ]
)
def test_container_image_exists(image, url):
    with patch("teuthology.util.containers.requests.get") as m_get:
        containers.container_image_exists(image)
        m_get.assert_called_once_with(url)


@pytest.mark.parametrize(
    'hash, flavor, base_image, rci_input',
    [
        ('hash', 'flavor', 'base-image', ':hash-base-image-flavor'),
        ('hash', 'default', 'centos:9', ':hash'),
        ('hash', 'default', 'rockylinux-10', ':hash-rockylinux-10'),
    ]
)
def test_container_image_for_hash(hash, flavor, base_image, rci_input):
    with patch('teuthology.util.containers.resolve_container_image') as m_rci:
        with patch('teuthology.util.containers.container_image_exists'):
            containers.container_image_for_hash(hash, flavor, base_image)
            m_rci.assert_called_once_with(rci_input)
