# #
# Copyright 2013-2014 Ghent University
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
# #

"""
The main easyconfig format class

@author: Stijn De Weirdt (Ghent University)
@author: Kenneth Hoste (Ghent University)
"""
import copy
import re
from vsc import fancylogger
from vsc.utils.missing import get_subclasses

from easybuild.framework.easyconfig.format.version import EasyVersion, OrderedVersionOperators
from easybuild.framework.easyconfig.format.version import ToolchainVersionOperator, VersionOperator
from easybuild.framework.easyconfig.format.convert import Dependency
from easybuild.tools.configobj import Section


# format is mandatory major.minor
FORMAT_VERSION_KEYWORD = "EASYCONFIGFORMAT"
FORMAT_VERSION_TEMPLATE = "%(major)s.%(minor)s"
FORMAT_VERSION_HEADER_TEMPLATE = "# %s %s\n" % (FORMAT_VERSION_KEYWORD, FORMAT_VERSION_TEMPLATE)  # must end in newline
FORMAT_VERSION_REGEXP = re.compile(r'^#\s+%s\s*(?P<major>\d+)\.(?P<minor>\d+)\s*$' % FORMAT_VERSION_KEYWORD, re.M)
FORMAT_DEFAULT_VERSION = EasyVersion('1.0')

_log = fancylogger.getLogger('easyconfig.format.format', fname=False)


def get_format_version(txt):
    """Get the easyconfig format version as EasyVersion instance."""
    res = FORMAT_VERSION_REGEXP.search(txt)
    format_version = None
    if res is not None:
        try:
            maj_min = res.groupdict()
            format_version = EasyVersion(FORMAT_VERSION_TEMPLATE % maj_min)
        except (KeyError, TypeError), err:
            _log.error("Failed to get version from match %s: %s" % (res.groups(), err))
    return format_version


class NestedDict(dict):
    """A nested dictionary, with tracking of depth and parent"""
    def __init__(self, parent, depth):
        dict.__init__(self)
        self.depth = depth
        self.parent = parent

    def get_nested_dict(self):
        """Return an instance of NestedDict with this instance as parent"""
        nd = NestedDict(parent=self.parent, depth=self.depth + 1)
        return nd

    def copy(self):
        """Return a copy. Any relation between key and value are deepcopied away."""
        nd = self.__class__(parent=self.parent, depth=self.depth)
        for key, val in self.items():
            cp_key = copy.deepcopy(key)
            if isinstance(val, NestedDict):
                cp_val = val.copy()
            else:
                cp_val = copy.deepcopy(val)
            nd[cp_key] = cp_val
        return nd


class TopNestedDict(NestedDict):
    """The top level nested dictionary (depth 0, parent is itself)"""
    def __init__(self, parent=None, depth=None):
        # parent and depth are ignored; just to support same init for copier
        NestedDict.__init__(self, self, 0)


class EBConfigObj(object):
    """
    Enhanced ConfigObj, version/toolchain and other easyconfig specific aspects aware

    Given ConfigObj instance, make instance that represents a parser

    Mandatory/minimal (to mimic v1.0 behaviour); first version/toolchain is the default
    [SUPPORTED]
    versions=version_operator
    toolchains=toolchain_version_operator

    Optional
    [DEFAULT]
    ...
    [<operatorX> <versionX>]
    ...
    [<toolchainA> <operatorA> <versionA>]
    [[<operatorY> <versionY>]]
    ...
    ...
    """
    SECTION_MARKER_DEFAULT = 'DEFAULT'
    SECTION_MARKER_DEPENDENCIES = 'DEPENDENCIES'
    SECTION_MARKER_SUPPORTED = 'SUPPORTED'
    # list of known marker types (except default)
    KNOWN_VERSION_MARKER_TYPES = [ToolchainVersionOperator, VersionOperator]  # order matters, see parse_sections
    VERSION_OPERATOR_VALUE_TYPES = {
        # toolchains: comma-separated list of toolchain version operators
        'toolchains': ToolchainVersionOperator,
        # versions: comma-separated list of version operators
        'versions': VersionOperator,
    }

    def __init__(self, configobj=None):
        """
        Initialise EBConfigObj instance
        @param configobj: ConfigObj instance
        """
        self.log = fancylogger.getLogger(self.__class__.__name__, fname=False)

        self.tcname = None

        self.default = {}  # default section
        self.supported = {}  # supported section
        self.sections = None  # all other sections
        self.unfiltered_sections = {}  # unfiltered other sections

        if configobj is not None:
            self.parse(configobj)

    def _init_sections(self):
        """Initialise self.sections. Make sure default and supported exist"""
        self.sections = TopNestedDict()
        for key in [self.SECTION_MARKER_DEFAULT, self.SECTION_MARKER_SUPPORTED]:
            self.sections[key] = self.sections.get_nested_dict()

    def parse_sections(self, toparse, current):
        """
        Parse Section instance; convert all supported sections, keys and values to their respective representations

        Returns a dict of (nested) Sections

        @param toparse: a Section (or ConfigObj) instance, basically a dict of (unparsed) sections
        @param current: a.k.a. the current level in the NestedDict 
        """
        # note: configobj already converts comma-separated strings in lists
        #
        # list of supported keywords, all else will fail
        special_keys = self.VERSION_OPERATOR_VALUE_TYPES.keys()

        self.log.debug('Processing current depth %s' % current.depth)

        for key, value in toparse.items():
            if isinstance(value, Section):
                self.log.debug("Enter subsection key %s value %s" % (key, value))


                # only supported types of section keys are:
                # * DEFAULT
                # * SUPPORTED
                # * dependencies
                # * VersionOperator or ToolchainVersionOperator (e.g. [> 2.0], [goolf > 1])
                if key in [self.SECTION_MARKER_DEFAULT, self.SECTION_MARKER_SUPPORTED]:
                    # parse value as a section, recursively
                    new_value = self.parse_sections(value, current.get_nested_dict())
                    self.log.debug('Converted %s section to new value %s' % (key, new_value))
                    current[key] = new_value

                elif key == self.SECTION_MARKER_DEPENDENCIES:
                    new_key = 'dependencies'
                    new_value = []
                    for dep_name, dep_val in value.items():
                        if isinstance(dep_val, Section):
                            self.log.error("Unsupported nested section '%s' found in dependencies section" % dep_name)
                        else:
                            # FIXME: parse the dependency specification for version, toolchain, suffix, etc.
                            dep = Dependency(dep_val, name=dep_name)
                            if dep.name() is None or dep.version() is None:
                                tmpl = "Failed to find name/version in parsed dependency: %s (dict: %s)"
                                self.log.error(tmpl % (dep, dict(dep)))
                            new_value.append(dep)

                    self.log.debug('Converted dependency section %s to %s, passed it to parent section (or default)' % (key, new_value))
                    if isinstance(current, TopNestedDict):
                        current[self.SECTION_MARKER_DEFAULT].update({new_key: new_value})
                    else:
                        current.parent[new_key] = new_value
                else:
                    # try parsing key as toolchain version operator first
                    # try parsing as version operator if it's not a toolchain version operator
                    for marker_type in self.KNOWN_VERSION_MARKER_TYPES:
                        new_key = marker_type(key)
                        if new_key:
                            self.log.debug("'%s' was parsed as a %s section marker" % (key, marker_type.__name__))
                            break
                        else:
                            self.log.debug("Not a %s section marker" % marker_type.__name__)
                    if not new_key:
                        self.log.error("Unsupported section marker '%s'" % key)

                    # parse value as a section, recursively
                    new_value = self.parse_sections(value, current.get_nested_dict())

                    self.log.debug('Converted section key %s value %s in new key %s new value %s' % (key, value, new_key, new_value))
                    current[new_key] = new_value

            else:
                # simply pass down any non-special key-value items
                if not key in special_keys:
                    self.log.debug('Passing down key %s with value %s' % (key, value))
                    new_value = value

                # parse individual key-value assignments
                elif key in self.VERSION_OPERATOR_VALUE_TYPES:
                    value_type = self.VERSION_OPERATOR_VALUE_TYPES[key]
                    # list of supported toolchains/versions
                    # first one is default
                    if isinstance(value, basestring):
                        # so the split should be unnecessary
                        # (if it's not a list already, it's just one value)
                        # TODO this is annoying. check if we can force this in configobj
                        value = value.split(',')
                    # remove possible surrounding whitespace (some people add space after comma)
                    new_value = [value_type(x.strip()) for x in value]
                    if False in [x.is_valid() for x in new_value]:
                        self.log.error("Failed to parse '%s' as list of %s" % (value, value_type.__name__))
                else:
                    tup = (key, value, type(value))
                    self.log.error('Bug: supported but unknown key %s with non-string value: %s, type %s' % tup)

                self.log.debug("Converted value '%s' for key '%s' into new value '%s'" % (value, key, new_value))
                current[key] = new_value

        return current

    def parse(self, configobj):
        """
        Parse configobj using using recursive parse_sections. 
        Then split off the default and supported sections. 

        @param configobj: ConfigObj instance
        """
        # keep reference to original (in case it's needed/wanted)
        self.configobj = configobj

        # process the configobj instance
        self._init_sections()
        self.sections = self.parse_sections(self.configobj, self.sections)

        # handle default section
        # no nesting
        #  - add DEFAULT key-value entries to the root of self.sections
        #  - key-value items from other sections will be deeper down
        #  - deepest level is best match and wins, so defaults are on top level
        self.default = self.sections.pop(self.SECTION_MARKER_DEFAULT)
        for key, value in self.default.items():
            self.sections[key] = value

        # handle supported section
        # supported should only have 'versions' and 'toolchains' keys
        self.supported = self.sections.pop(self.SECTION_MARKER_SUPPORTED)
        for key, value in self.supported.items():
            if not key in self.VERSION_OPERATOR_VALUE_TYPES:
                self.log.error('Unsupported key %s in %s section' % (key, self.SECTION_MARKER_SUPPORTED))
            self.sections['%s' % key] = value

        for key, supported_key, fn_name in [('version', 'versions', 'get_version_str'),
                                            ('toolchain', 'toolchains', 'as_dict')]:
            if supported_key in self.supported:
                self.log.debug('%s in supported, trying to detemine default for %s' % (supported_key, key))
                first = self.supported[supported_key][0]
                f_val = getattr(first, fn_name)()
                if f_val is None:
                    self.log.warning("First %s %s can't be used as default (%s retuned None)" % (key, first, fn_name))
                else:
                    self.log.debug('Using first %s (%s) as default %s' % (key, first, f_val))
                    self.default[key] = f_val

        self.log.debug("(parse) supported: %s" % self.supported)
        self.log.debug("(parse) default: %s" % self.default)
        self.log.debug("(parse) sections: %s" % self.sections)

    def squash(self, tcname, tcversion, version):
        """
        Project the multidimensional easyconfig to single easyconfig
        It (tries to) detect conflicts in the easyconfig.

        @param version: version to keep
        @param tcname: toolchain name to keep
        @param tcversion: toolchain version to keep
        """
        self.log.debug('Start squash with sections %s' % self.sections)

        # dictionary to keep track of all sections, to detect conflicts in the easyconfig
        sanity = {
            'versops': OrderedVersionOperators(),
            'toolchains': {},
        }

        oversops, res = self._squash(tcname, tcversion, version, self.sections, sanity)
        self.log.debug('Temp result versions %s result %s' % (oversops, res))
        self.log.debug('Temp result versions data %s' % (oversops.datamap))
        # update res, most strict matching versionoperator should be first
        # so update in reversed order
        for versop in oversops.versops[::-1]:
            res.update(oversops.get_data(versop))

        self.log.debug('End squash with result %s' % res)
        return res

    def _squash(self, tcname, tcversion, version, processed, sanity):
        """
        Project the multidimensional easyconfig (or subsection thereof) to single easyconfig
        Returns dictionary res with squashed data for the processed block.

        @param version: version to keep
        @param tcname: toolchain name to keep
        @param tcversion: toolchain version to keep
        @param processed: easyconfig (Top)NestedDict
        @param sanity: dictionary to keep track of section markers and detect conflicts 
        """
        res = {}

        res_sections = {}

        # a OrderedVersionOperators instance to keep track of the data of the matching version sections
        oversops = OrderedVersionOperators()

        self.log.debug('Start processed %s' % (processed))
        # walk over dictionary of parsed sections, and check for marker conflicts (using .add())
        for key, value in processed.items():
            if isinstance(value, NestedDict):
                if isinstance(key, ToolchainVersionOperator):
                    # perform sanity check for all toolchains, use .add to check for conflicts
                    tc_overops = sanity['toolchains'].setdefault(key.tc_name, OrderedVersionOperators())
                    tc_overops.add(key)

                    if key.test(tcname, tcversion):
                        tup = (tcname, tcversion, key)
                        self.log.debug("Found matching marker for specified toolchain '%s, %s': %s" % tup)
                        tmp_res_oversops, tmp_res_version = self._squash(tcname, tcversion, version, value, sanity)
                        res_sections.update(tmp_res_version)
                        for versop in tmp_res_oversops.versops:
                            oversops.add(versop, tmp_res_oversops.get_data(versop), update=True)
                    else:
                        self.log.debug("Found marker for other toolchain or other version '%s', ignoring it." % key)
                elif isinstance(key, VersionOperator):
                    # keep track of all version operators, and enforce conflict check
                    sanity['versops'].add(key)
                    if key.test(version):
                        self.log.debug('Found matching version marker %s' % key)
                        tmp_res_oversops, tmp_res_version = self._squash(tcname, tcversion, version, value, sanity)
                        # don't update res_sections
                        # add this to a orderedversop that has matching versops.
                        # data in this matching orderedversop must be updated to the res at the end
                        for versop in tmp_res_oversops.versops:
                            oversops.add(versop, tmp_res_oversops.get_data(versop), update=True)
                        oversops.add(key, tmp_res_version, update=True)
                    else:
                        self.log.debug('Found non-matching version marker %s. Ignoring it.' % key)
                else:
                    self.log.error("Unhandled section marker '%s' (type '%s')" % (key, type(key)))

            elif key in self.VERSION_OPERATOR_VALUE_TYPES:
                self.log.debug("Found VERSION_OPERATOR_VALUE_TYPES entry (%s)" % key)
                if key == 'toolchains':
                    # remove any other toolchain from list
                    self.log.debug("Filtering 'toolchains' key")

                    matching_toolchains = []
                    for tcversop in value:
                        tc_overops = sanity['toolchains'].setdefault(tcversop.tc_name, OrderedVersionOperators())
                        tc_overops.add(tcversop)
                        if tcversop.test(tcname, tcversion):
                            matching_toolchains.append(tcversop)

                    if matching_toolchains:
                        # does this have any use?
                        self.log.debug('Matching toolchains %s found (but data not needed)' % matching_toolchains)
                    else:
                        self.log.debug('No matching toolchains, removing the whole current key %s' % key)
                        return OrderedVersionOperators(), {}

                elif key == 'versions':
                    self.log.debug("Adding all versions %s from versions key" % (value))
                    matching_versions = []
                    for versop in value:
                        sanity['versops'].add(versop)
                        if versop.test(version):
                            matching_versions.append(versop)
                    if matching_versions:
                        # does this have any use?
                        self.log.debug('Matching versions %s found (but data not needed)' % matching_versions)
                    else:
                        self.log.debug('No matching versions, removing the whole current key %s' % key)
                        return OrderedVersionOperators(), {}
                else:
                    self.log.debug('Adding regular VERSION_OPERATOR_VALUE_TYPES key %s value %s' % (key, value))
                    res[key] = value
            else:
                    self.log.debug('Adding key %s value %s' % (key, value))
                    res[key] = value

        # merge the current attributes with higher level ones, higher level ones win
        # TODO figure out ordered processing of sections?
        self.log.debug('Current level result %s' % (res))
        self.log.debug('Higher level sections result %s' % (res_sections))

        res.update(res_sections)

        self.log.debug('End processed %s ordered versions %s result %s' % (processed, oversops, res))
        return oversops, res

    def get_specs_for(self, version=None, tcname=None, tcversion=None):
        """
        Return dictionary with specifications listed in sections applicable for specified info.
        """

        # make sure that requested version/toolchain are supported by this easyconfig
        versions = [x.get_version_str() for x in self.supported['versions']]
        if version is None:
            self.log.debug("No version specified")
        elif version in versions:
            self.log.debug("Version '%s' is supported in easyconfig." % version)
        else:
            self.log.error("Version '%s' not supported in easyconfig (only %s)" % (version, versions))

        tcnames = [tc.tc_name for tc in self.supported['toolchains']]
        if tcname is None:
            self.log.debug("Toolchain name not specified.")
        elif tcname in tcnames:
            self.log.debug("Toolchain '%s' is supported in easyconfig." % tcname)
            tcversions = [tc.get_version_str() for tc in self.supported['toolchains'] if tc.tc_name == tcname]
            if tcversion is None:
                self.log.debug("Toolchain version not specified.")
            elif tcversion in tcversions:
                self.log.debug("Toolchain '%s' version '%s' is supported in easyconfig" % (tcname, tcversion))
            else:
                tup = (tcname, tcversion, tcversions)
                self.log.error("Toolchain '%s' version '%s' not supported in easyconfig (only %s)" % tup)
        else:
            self.log.error("Toolchain '%s' not supported in easyconfig (only %s)" % (tcname, tcnames))

        # TODO: determine 'path' to take in sections based on version and toolchain version

        return self.default


class EasyConfigFormat(object):
    """EasyConfigFormat class"""
    VERSION = EasyVersion('0.0')  # dummy EasyVersion instance (shouldn't be None)
    USABLE = False  # disable this class as usable format

    def __init__(self):
        """Initialise the EasyConfigFormat class"""
        self.log = fancylogger.getLogger(self.__class__.__name__, fname=False)

        if not len(self.VERSION) == len(FORMAT_VERSION_TEMPLATE.split('.')):
            self.log.error('Invalid version number %s (incorrect length)' % self.VERSION)

        self.rawtext = None  # text version of the easyconfig
        self.header = None  # easyconfig header (e.g., format version, license, ...)
        self.docstring = None  # easyconfig docstring (e.g., author, maintainer, ...)

        self.specs = {}

    def set_specifications(self, specs):
        """Set specifications."""
        self.log.debug('Set copy of specs %s' % specs)
        self.specs = copy.deepcopy(specs)

    def get_config_dict(self):
        """Returns a single easyconfig dictionary."""
        raise NotImplementedError

    def validate(self):
        """Verify the easyconfig format"""
        raise NotImplementedError

    def parse(self, txt, **kwargs):
        """Parse the txt according to this format. This is highly version specific"""
        raise NotImplementedError

    def dump(self):
        """Dump easyconfig according to this format. This is higly version specific"""
        raise NotImplementedError


def get_format_version_classes(version=None):
    """Return the (usable) subclasses from EasyConfigFormat that have a matching version."""
    all_classes = get_subclasses(EasyConfigFormat)
    if version is None:
        return all_classes
    else:
        return [x for x in all_classes if x.VERSION == version and x.USABLE]
