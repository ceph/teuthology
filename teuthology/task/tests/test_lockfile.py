"""
Tests for teuthology.task.lockfile module
"""
import pytest
from unittest.mock import Mock, MagicMock, patch
from teuthology.task import lockfile


class TestLockfileAsyncioMigration:
    """Test that lockfile module works with asyncio instead of gevent"""
    
    def test_event_loop_manager_initialization(self):
        """Test that EventLoopManager can be created"""
        manager = lockfile._EventLoopManager()
        assert manager._loop is None
        assert manager._thread is None
        assert not manager._started
    
    def test_event_loop_manager_start_stop(self):
        """Test that EventLoopManager can start and stop"""
        manager = lockfile._EventLoopManager()
        manager.start()
        assert manager._started
        assert manager._loop is not None
        assert manager._thread is not None
        manager.stop()
    
    def test_task_handle_creation(self):
        """Test that TaskHandle can be created with a coroutine"""
        import asyncio
        
        async def dummy_coro():
            return "test_result"
        
        manager = lockfile._EventLoopManager()
        manager.start()
        
        try:
            handle = lockfile._TaskHandle(manager.loop, dummy_coro())
            result = handle.get()
            assert result == "test_result"
        finally:
            manager.stop()
    
    def test_async_timeout_initialization(self):
        """Test that AsyncTimeout can be created"""
        timeout = lockfile._AsyncTimeout(seconds=5.0)
        assert timeout.seconds == 5.0
        assert not timeout._cancelled
        timeout.start()
        timeout.cancel()
        assert timeout._cancelled
    
    def test_spawn_function(self):
        """Test that spawn can execute a function"""
        def test_func(x, y):
            return x + y
        
        manager = lockfile._EventLoopManager()
        try:
            handle = manager.spawn(test_func, 2, 3)
            result = handle.get()
            assert result == 5
        finally:
            manager.stop()
    
    def test_task_handle_kill(self):
        """Test that TaskHandle can be killed"""
        import asyncio
        import time
        
        async def long_running_coro():
            await asyncio.sleep(10)
            return "should_not_reach"
        
        manager = lockfile._EventLoopManager()
        manager.start()
        
        try:
            handle = lockfile._TaskHandle(manager.loop, long_running_coro())
            time.sleep(0.1)  # Let it start
            handle.kill(block=True)
            assert handle._killed
        finally:
            manager.stop()


class TestLockfileTask:
    """Test the main lockfile task function"""
    
    def test_task_requires_list_config(self):
        """Test that task validates config is a list"""
        ctx = Mock()
        config = {"not": "a list"}
        
        with pytest.raises(AssertionError, match="task lockfile got invalid config"):
            lockfile.task(ctx, config)
    
    def test_task_validates_dict_entries(self):
        """Test that task validates dictionary entries have required fields"""
        ctx = Mock()
        ctx.cluster = Mock()
        
        # Missing required fields - will raise KeyError when accessing 'lockfile'
        config = [{"client": "client.0"}]  # Missing lockfile and holdtime
        
        with pytest.raises(KeyError, match="lockfile"):
            lockfile.task(ctx, config)

# Made with Bob
