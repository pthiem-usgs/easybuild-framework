##
# Copyright 2016 Ghent University
#
# This file is part of EasyBuild,
# originally created by the HPC team of Ghent University (http://ugent.be/hpc/en),
# with support of Ghent University (http://ugent.be/hpc),
# the Flemish Supercomputer Centre (VSC) (https://vscentrum.be/nl/en),
# the Hercules foundation (http://www.herculesstichting.be/in_English)
# and the Department of Economy, Science and Innovation (EWI) (http://www.ewi-vlaanderen.be/en).
#
# http://github.com/hpcugent/easybuild
#
# EasyBuild is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation v2.
#
# EasyBuild is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with EasyBuild.  If not, see <http://www.gnu.org/licenses/>.
##
"""
Style tests for easyconfig files using pep8.

@author: Ward Poelmans (Ghent University)
"""

import re
from vsc.utils import fancylogger

from easybuild.tools.utilities import only_if_module_is_available

try:
    import pep8
except ImportError:
    pass

_log = fancylogger.getLogger('easyconfig.style', fname=False)


# any function starting with eb_check_ will be added to the tests
# if the test number is added to the select list. The test number is
# definied as AXXX where A is either E or W and XXX is a 3 digit number.
# It should be mentioned in the docstring as a single word.
# Read the pep8 docs to understand the arguments of these functions
def eb_check_trailing_whitespace(physical_line, lines, line_number, total_lines):
    """
    W299
    Warn about trailing whitespace, expect for the description and comments.
    This differs from the standard trailing whitespace check as that
    will will warn for any trailing whitespace.
    """
    comment_re = re.compile('^\s*#')
    if comment_re.match(physical_line):
        return None

    result = pep8.trailing_whitespace(physical_line)
    if result:
        result = (result[0], result[1].replace("W291", "W299"))

    # if the warning is about the multiline string of description
    # we will not issue a warning
    keys_re = re.compile("^(?P<key>[a-z_]+)\s*=\s*")

    for line in reversed(lines[0:line_number]):
        res = keys_re.match(line)
        if res:
            if res.group("key") == "description":
                return None
            else:
                break

    return result


@only_if_module_is_available('pep8')
def test_style_conformance(lst_easyconfigs, verbose=False):
    """
    Check the given list of easyconfigs for style
    @param lst_easyconfigs list of file paths to easyconfigs
    @param verbose print our statistics and be verbose about the errors and warning
    @return the number of warnings and errors
    """
    # importing autopep8 fucks up pep8. We reload it just to be sure
    reload(pep8)

    # register the extra checks before using pep8:
    # any function in this module starting with `eb_check_` will be used.
    cands = globals()
    for check_function in sorted([cands[f] for f in cands if callable(cands[f]) and f.startswith('eb_check_')]):
        pep8.register_check(check_function)

    pep8style = pep8.StyleGuide(quiet=False, config_file=None)
    options = pep8style.options
    options.max_line_length = 120
    # we ignore some tests
    # note that W291 has be replaced by our custom W299
    options.ignore = ('E402',  # import not on top
                      'W291',  # replaced by W299
                      'E501',  # line too long
                      )
    if verbose:
        options.verbose = 1
    else:
        options.verbose = 0

    result = pep8style.check_files(lst_easyconfigs)

    if verbose:
        result.print_statistics()

    return result.total_errors
