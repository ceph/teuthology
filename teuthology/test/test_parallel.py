import pytest

from teuthology.parallel import parallel


def identity(item, input_set=None, remove=False):
    if input_set is not None:
        assert item in input_set
        if remove:
            input_set.remove(item)
    return item


class TestParallel(object):
    @pytest.mark.asyncio
    async def test_basic(self):
        in_set = set(range(10))
        async with parallel() as para:
            for i in in_set:
                para.spawn(identity, i, in_set, remove=True)
                assert para.any_spawned is True
            assert para.count == len(in_set)

    @pytest.mark.asyncio
    async def test_result(self):
        in_set = set(range(10))
        async with parallel() as para:
            for i in in_set:
                para.spawn(identity, i, in_set)
            async for result in para:
                print(f"res in test = {result}")
                in_set.remove(result)

