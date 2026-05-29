"""
Tests for teuthology.task.proc_thrasher module
"""
import pytest
import time
from unittest.mock import Mock, MagicMock, patch, call
from teuthology.task.proc_thrasher import ProcThrasher


class TestProcThrasher:
    """Test the ProcThrasher class."""
    
    def test_init(self):
        """Test ProcThrasher initialization."""
        config = {
            'num_procs': 3,
            'rest_period': 50,
            'run_time': 500
        }
        remote = Mock()
        
        thrasher = ProcThrasher(config, remote, 'arg1', 'arg2', kwarg1='val1')
        
        assert thrasher.config == config
        assert thrasher.remote == remote
        assert thrasher.proc_args == ('arg1', 'arg2')
        assert thrasher.proc_kwargs == {'kwarg1': 'val1'}
        assert thrasher.num_procs == 3
        assert thrasher.rest_period == 50
        assert thrasher.run_time == 500
        assert thrasher._task is None
        assert thrasher._loop is None
        assert thrasher._loop_thread is None
        assert thrasher._started is False
    
    def test_init_defaults(self):
        """Test ProcThrasher initialization with default values."""
        config = {}
        remote = Mock()
        
        thrasher = ProcThrasher(config, remote)
        
        assert thrasher.num_procs == 5
        assert thrasher.rest_period == 100
        assert thrasher.run_time == 1000
    
    def test_init_custom_logger(self):
        """Test ProcThrasher initialization with custom logger."""
        config = {}
        remote = Mock()
        custom_logger = Mock()
        
        thrasher = ProcThrasher(config, remote, logger=custom_logger)
        
        assert thrasher.logger == custom_logger
    
    def test_log(self):
        """Test log method."""
        config = {}
        remote = Mock()
        mock_logger = Mock()
        
        thrasher = ProcThrasher(config, remote, logger=mock_logger)
        thrasher.log("test message")
        
        mock_logger.info.assert_called_once_with("test message")
    
    def test_start_creates_event_loop(self):
        """Test that start() creates an event loop."""
        config = {'run_time': 0}  # Short run time for testing
        remote = Mock()
        
        thrasher = ProcThrasher(config, remote)
        
        assert thrasher._started is False
        assert thrasher._loop is None
        assert thrasher._loop_thread is None
        
        thrasher.start()
        
        # Give the thread time to start
        time.sleep(0.1)
        
        assert thrasher._started is True
        assert thrasher._loop is not None
        assert thrasher._loop_thread is not None
        assert thrasher._loop_thread.is_alive()
        assert thrasher._task is not None
        
        # Clean up
        thrasher.join()
    
    def test_start_idempotent(self):
        """Test that calling start() multiple times is safe."""
        config = {'run_time': 0}
        remote = Mock()
        
        thrasher = ProcThrasher(config, remote)
        
        thrasher.start()
        first_task = thrasher._task
        
        # Call start again
        thrasher.start()
        
        # Should be the same task
        assert thrasher._task is first_task
        
        # Clean up
        thrasher.join()
    
    def test_join_without_start(self):
        """Test that join() without start() is safe."""
        config = {}
        remote = Mock()
        
        thrasher = ProcThrasher(config, remote)
        
        # Should not raise
        thrasher.join()
    
    def test_cleanup(self):
        """Test that cleanup properly stops the event loop."""
        config = {'run_time': 0}
        remote = Mock()
        
        thrasher = ProcThrasher(config, remote)
        thrasher.start()
        
        # Give it time to start
        time.sleep(0.1)
        
        assert thrasher._loop is not None
        assert thrasher._loop.is_running()
        
        thrasher.join()
        
        # Give it time to clean up
        time.sleep(0.2)
        
        # Loop should be stopped and closed
        assert thrasher._loop.is_closed()


# Made with Bob