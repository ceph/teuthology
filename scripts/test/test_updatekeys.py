from script import Script
import docopt
from pytest import raises
from pytest import skip
from scripts import updatekeys


class TestUpdatekeys(Script):
    script_name = 'teuthology-updatekeys'
    script_module = 'scripts.updatekeys'

    def test_invalid(self):
        skip("teuthology.lock needs to be partially refactored to allow" +
             "teuthology-updatekeys to return nonzero in all erorr cases")

    def test_all_and_targets(self):
        with raises(docopt.DocoptExit):
            docopt.docopt(updatekeys.doc, ['-a', '-t', 'foo'])

    def test_no_args(self):
        with raises(docopt.DocoptExit):
            docopt.docopt(updatekeys.doc, [])
