"""
Tests for teuthology.task.pexec module
"""
import pytest
from unittest.mock import Mock, MagicMock, patch, call
from teuthology.task import pexec


class TestSyncQueue:
    """Test the _SyncQueue compatibility wrapper."""
    
    def test_basic_put_get(self):
        """Test basic put and get operations."""
        queue = pexec._SyncQueue(maxsize=5)
        queue.put("item1")
        queue.put("item2")
        
        assert queue.get() == "item1"
        assert queue.get() == "item2"
    
    def test_empty(self):
        """Test empty() method."""
        queue = pexec._SyncQueue()
        assert queue.empty() is True
        
        queue.put("item")
        assert queue.empty() is False
        
        queue.get()
        assert queue.empty() is True
    
    def test_full(self):
        """Test full() method with bounded queue."""
        queue = pexec._SyncQueue(maxsize=2)
        assert queue.full() is False
        
        queue.put("item1")
        assert queue.full() is False
        
        queue.put("item2")
        assert queue.full() is True
        
        queue.get()
        assert queue.full() is False
    
    def test_fifo_order(self):
        """Test that queue maintains FIFO order."""
        queue = pexec._SyncQueue()
        items = ["first", "second", "third"]
        
        for item in items:
            queue.put(item)
        
        for expected in items:
            assert queue.get() == expected


class TestSyncEvent:
    """Test the _SyncEvent compatibility wrapper."""
    
    def test_set_and_wait(self):
        """Test basic set and wait operations."""
        event = pexec._SyncEvent()
        
        # Event should not be set initially
        assert event.wait(timeout=0.1) is False
        
        # Set the event
        event.set()
        
        # Now wait should succeed immediately
        assert event.wait(timeout=0.1) is True
    
    def test_clear(self):
        """Test clear operation."""
        event = pexec._SyncEvent()
        
        event.set()
        assert event.wait(timeout=0.1) is True
        
        event.clear()
        assert event.wait(timeout=0.1) is False
    
    def test_multiple_waiters(self):
        """Test that multiple threads can wait on the same event."""
        import threading
        
        event = pexec._SyncEvent()
        results = []
        
        def waiter(idx):
            if event.wait(timeout=2.0):
                results.append(idx)
        
        threads = [threading.Thread(target=waiter, args=(i,)) for i in range(3)]
        for t in threads:
            t.start()
        
        # Give threads time to start waiting
        import time
        time.sleep(0.1)
        
        # Set the event - all waiters should proceed
        event.set()
        
        for t in threads:
            t.join(timeout=1.0)
        
        assert len(results) == 3
        assert set(results) == {0, 1, 2}


class TestBarrierFunctions:
    """Test barrier synchronization functions."""
    
    def test_init_barrier(self):
        """Test _init_barrier function."""
        queue = pexec._SyncQueue(maxsize=3)
        remote = Mock()
        
        pexec._init_barrier(queue, remote)
        
        assert queue.get() == remote
        assert queue.empty() is True
    
    def test_do_barrier_simple(self):
        """Test _do_barrier with two remotes."""
        queue = pexec._SyncQueue(maxsize=2)
        barrier = pexec._SyncEvent()
        remote1 = Mock(name="remote1")
        remote2 = Mock(name="remote2")
        
        # Initialize barrier
        pexec._init_barrier(queue, remote1)
        pexec._init_barrier(queue, remote2)
        
        # First remote hits barrier
        import threading
        
        def first_barrier():
            pexec._do_barrier(barrier, queue, remote1)
        
        t1 = threading.Thread(target=first_barrier)
        t1.start()
        
        # Give first thread time to wait
        import time
        time.sleep(0.1)
        
        # Second remote hits barrier - should release both
        pexec._do_barrier(barrier, queue, remote2)
        
        t1.join(timeout=1.0)
        assert not t1.is_alive()


class TestGenerateRemotes:
    """Test _generate_remotes function."""
    
    def test_all_config(self):
        """Test 'all' configuration."""
        ctx = Mock()
        remote1 = Mock(name="remote1")
        remote2 = Mock(name="remote2")
        ctx.cluster.remotes.keys.return_value = [remote1, remote2]
        
        config = {'all': ['command1', 'command2']}
        
        remotes = list(pexec._generate_remotes(ctx, config))
        
        assert len(remotes) == 2
        assert remotes[0] == (remote1, ['command1', 'command2'])
        assert remotes[1] == (remote2, ['command1', 'command2'])
    
    def test_clients_config(self):
        """Test 'clients' configuration."""
        ctx = Mock()
        remote1 = Mock(name="remote1")
        remote2 = Mock(name="remote2")
        
        # Mock cluster.only to return appropriate remotes
        def only_side_effect(role):
            mock_cluster = Mock()
            if 'client.0' in role:
                mock_cluster.remotes.keys.return_value = [remote1]
            elif 'client.1' in role:
                mock_cluster.remotes.keys.return_value = [remote2]
            return mock_cluster
        
        ctx.cluster.only.side_effect = only_side_effect
        
        with patch('teuthology.task.pexec.teuthology.all_roles_of_type') as mock_roles:
            mock_roles.return_value = ['0', '1']
            
            config = {'clients': ['client_command']}
            
            remotes = list(pexec._generate_remotes(ctx, config))
            
            assert len(remotes) == 2
            assert remotes[0] == (remote1, ['client_command'])
            assert remotes[1] == (remote2, ['client_command'])
    
    def test_specific_roles_config(self):
        """Test specific role configuration."""
        ctx = Mock()
        remote1 = Mock(name="remote1")
        remote2 = Mock(name="remote2")
        
        def only_side_effect(role):
            mock_cluster = Mock()
            if 'mon.0' in role:
                mock_cluster.remotes.keys.return_value = [remote1]
            elif 'osd.0' in role:
                mock_cluster.remotes.keys.return_value = [remote2]
            return mock_cluster
        
        ctx.cluster.only.side_effect = only_side_effect
        
        config = {
            'mon.0': ['mon_command'],
            'osd.0': ['osd_command']
        }
        
        remotes = list(pexec._generate_remotes(ctx, config))
        
        assert len(remotes) == 2
        assert remotes[0] == (remote1, ['mon_command'])
        assert remotes[1] == (remote2, ['osd_command'])


class TestExecHost:
    """Test _exec_host function."""
    
    @patch('teuthology.task.pexec.tor.wait')
    def test_exec_host_basic(self, mock_wait):
        """Test basic command execution."""
        barrier = pexec._SyncEvent()
        barrier_queue = pexec._SyncQueue(maxsize=1)
        
        remote = Mock()
        mock_process = Mock()
        mock_stdin = Mock()
        mock_process.stdin = mock_stdin
        remote.run.return_value = mock_process
        remote.name = "test_remote"
        
        commands = ['echo hello', 'echo world']
        
        pexec._exec_host(barrier, barrier_queue, remote, False, '/test', commands)
        
        # Verify remote.run was called
        remote.run.assert_called_once()
        call_args = remote.run.call_args
        assert 'TESTDIR=/test' in call_args[1]['args']
        assert 'bash' in call_args[1]['args']
        
        # Verify commands were written to stdin
        assert mock_stdin.writelines.call_count >= 2
        mock_stdin.flush.assert_called()
        mock_stdin.close.assert_called_once()
        
        # Verify wait was called
        mock_wait.assert_called_once()
    
    @patch('teuthology.task.pexec.tor.wait')
    def test_exec_host_with_sudo(self, mock_wait):
        """Test command execution with sudo."""
        barrier = pexec._SyncEvent()
        barrier_queue = pexec._SyncQueue(maxsize=1)
        
        remote = Mock()
        mock_process = Mock()
        mock_stdin = Mock()
        mock_process.stdin = mock_stdin
        remote.run.return_value = mock_process
        remote.name = "test_remote"
        
        commands = ['echo hello']
        
        pexec._exec_host(barrier, barrier_queue, remote, True, '/test', commands)
        
        # Verify sudo was added to args
        call_args = remote.run.call_args
        assert 'sudo' in call_args[1]['args']
        assert call_args[1]['args'][0] == 'sudo'


class TestPexecTask:
    """Test the main pexec task function."""
    
    @patch('teuthology.task.pexec.parallel')
    @patch('teuthology.task.pexec.teuthology.get_testdir')
    def test_task_basic(self, mock_get_testdir, mock_parallel_class):
        """Test basic task execution."""
        mock_get_testdir.return_value = '/test/dir'
        
        # Setup mock parallel context
        mock_parallel = Mock()
        mock_parallel_class.return_value.__enter__.return_value = mock_parallel
        mock_parallel_class.return_value.__exit__.return_value = True
        
        ctx = Mock()
        remote1 = Mock(name="remote1")
        ctx.cluster.remotes.keys.return_value = [remote1]
        
        config = {
            'all': ['command1', 'command2']
        }
        
        pexec.task(ctx, config)
        
        # Verify parallel.spawn was called
        assert mock_parallel.spawn.call_count == 1
        
        # Verify spawn was called with correct function
        spawn_call = mock_parallel.spawn.call_args
        assert spawn_call[0][0] == pexec._exec_host
    
    @patch('teuthology.task.pexec.parallel')
    @patch('teuthology.task.pexec.teuthology.get_testdir')
    def test_task_with_sudo(self, mock_get_testdir, mock_parallel_class):
        """Test task with sudo option."""
        mock_get_testdir.return_value = '/test/dir'
        
        mock_parallel = Mock()
        mock_parallel_class.return_value.__enter__.return_value = mock_parallel
        mock_parallel_class.return_value.__exit__.return_value = True
        
        ctx = Mock()
        remote1 = Mock(name="remote1")
        ctx.cluster.remotes.keys.return_value = [remote1]
        
        config = {
            'sudo': True,
            'all': ['command1']
        }
        
        pexec.task(ctx, config)
        
        # Verify spawn was called with sudo=True
        spawn_call = mock_parallel.spawn.call_args
        # Args are: _exec_host, barrier, barrier_queue, remote, sudo, testdir, commands
        assert spawn_call[0][4] is True  # sudo parameter (5th positional arg, index 4)
    
    def test_task_invalid_config(self):
        """Test task with invalid config."""
        ctx = Mock()
        config = "invalid"  # Should be dict
        
        with pytest.raises(AssertionError, match="task pexec got invalid config"):
            pexec.task(ctx, config)

# Made with Bob
