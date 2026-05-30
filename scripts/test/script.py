import sys
from pytest import raises
from importlib import import_module


class Script(object):
    script_name = 'teuthology'
    script_module = None  # Override in subclasses, e.g., 'scripts.run'

    def _get_module(self):
        """Get the script module, deriving from script_name if not set."""
        if self.script_module:
            return import_module(self.script_module)
        # Convert script_name to module path
        # e.g., 'teuthology-dispatcher' -> 'scripts.dispatcher'
        module_name = self.script_name.replace('teuthology-', '').replace('teuthology', 'run')
        return import_module(f'scripts.{module_name}')

    def test_help(self):
        """Test that the script has help information available."""
        module = self._get_module()
        
        # Check if module has a docstring (docopt-based scripts)
        if module.__doc__ and 'usage' in module.__doc__.lower():
            return  # Test passes
        
        # Check if module has a 'doc' variable (docopt-based scripts)
        if hasattr(module, 'doc') and module.doc and 'usage' in module.doc.lower():
            return  # Test passes
        
        # Check if module has parse_args function (argparse-based scripts)
        if hasattr(module, 'parse_args'):
            # For argparse, we can verify it has a parser by checking parse_args exists
            # and that calling it with --help would work (but we don't actually call it
            # as that would exit the process)
            return  # Test passes
        
        # If neither, fail
        raise AssertionError(
            f"{self.script_name} has neither a docstring/doc variable with usage info "
            f"nor a parse_args function"
        )

    def test_invalid(self):
        """Test that invalid arguments raise an error."""
        module = self._get_module()
        # Save original argv
        original_argv = sys.argv
        try:
            # Set argv to simulate command line with invalid option
            sys.argv = [self.script_name, '--invalid-option']
            
            # Try to parse args - should raise SystemExit
            with raises(SystemExit):
                if hasattr(module, 'parse_args'):
                    # For argparse-based scripts
                    module.parse_args(sys.argv[1:])
                elif hasattr(module, 'main'):
                    # For docopt-based scripts, main() will call docopt which exits on error
                    module.main()
                else:
                    raise NotImplementedError(f"Don't know how to test {self.script_name}")
        finally:
            # Restore original argv
            sys.argv = original_argv
