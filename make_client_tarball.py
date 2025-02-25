#!/usr/bin/env python
from __future__ import print_function
import sys

import os
from optparse import OptionParser
import shutil
import tempfile
import subprocess
try:
    import ConfigParser
except ImportError:
    import configparser as ConfigParser

try:
    from shutil import which as find_executable
except ImportError:  # Python 2:
    from distutils.spawn import find_executable


# make sure we can find our imports
if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


import stage1
import stage2

from common import *
import yumconf


BUNDLES_FILE = 'bundles.ini'


def check_running_as_root():
    if os.getuid() != 0:
        errormsg("Error: You need to be root to run this script")
        return False
    return True


def check_tools():
    ret = True
    for tool in ["patch", "find", "tar", "rpm", "yum", "yumdownloader"]:
        if not find_executable(tool):
            errormsg("Required executable '%s' not found" % tool)
            ret = False
    return ret


def check_yum_priorities():
    ret = subprocess.call(['rpm', '-q', 'dnf'])
    if ret == 0:  # dnf doesn't need yum-priorities
        return True
    ret = subprocess.call(['rpm', '--whatprovides', '-q', 'yum-priorities'])
    if ret != 0:
        errormsg("Error: nothing is providing yum-priorities")
        return False
    return True

def get_repofile(prog_dir, bundlecfg, bundle, basearch, dver):
    return os.path.join(prog_dir, bundlecfg.get(bundle, 'repofile') % {'basearch': basearch, 'dver': dver})

def make_tarball(bundlecfg, bundle, basearch, dver, packages, patch_dirs, prog_dir, stage_dir, relnum="0", extra_repos=None, version=None):
    """Run all the steps to make a non-root tarball.
    Returns (success (bool), tarball_path (relative), tarball_size (in bytes))

    """
    repofile = get_repofile(prog_dir, bundlecfg, bundle, basearch=basearch, dver=dver)

    extra_repos = extra_repos or []

    with yumconf.YumInstaller(repofile, dver, basearch, extra_repos) as yum:
        if not version:
            if bundlecfg.has_option(bundle, 'versionrpm'):
                version = yum.repoquery(bundlecfg.get(bundle, 'versionrpm'), "--queryformat=%{VERSION}").rstrip()
            else:
                version = 'unknown'
        tarball_path = bundlecfg.get(bundle, 'tarballname') % locals()

        post_scripts_dir = os.path.join(prog_dir, "post-install")

        statusmsg("Making stage 2 tarball for %s" % (packages))
        if not stage2.make_stage2_tarball(
                stage_dir        = stage_dir,
                packages         = packages,
                tarball          = tarball_path,
                patch_dirs       = patch_dirs,
                post_scripts_dir = post_scripts_dir,
                repofile         = repofile,
                dver             = dver,
                basearch         = basearch,
                relnum           = relnum,
                extra_repos      = extra_repos):
            errormsg("Making stage 2 tarball for %s unsuccessful. Files have been left in %r" % (packages, stage_dir))
            return (False, None, 0)
        tarball_size = os.stat(tarball_path)[6]
        return (True, tarball_path, tarball_size)


def parse_cmdline_args(argv):
    parser = OptionParser("""
    %prog [options] --osgver=<osgver> --dver=<dver> [--basearch=<basearch>]
or: %prog [options] --osgver=<osgver> --all
""")
    parser.add_option("-o", "--osgver", help="OSG Major Version (e.g 3.4). Either this or --bundle must be specified.")
    parser.add_option("--version", default=None, help="Version of the tarball; will be taken from the versionrpm of the bundle, e.g. osg-version, if not specified")
    parser.add_option("-r", "--relnum", default="1", help="Release number. Default is %default.")
    parser.add_option("--prerelease", default=True, action="store_true", help="Take packages from the prerelease repository (the default)")
    parser.add_option("--no-prerelease", "--noprerelease", dest="prerelease", action="store_false", help="Do not take packages from the prerelease repository")
    parser.add_option("-d", "--dver", help="Build tarball for this distro version. Must be one of (" + ", ".join(VALID_DVERS) + ")")
    parser.add_option("-b", "--basearch", help="Build tarball for this base architecture. Must be one of (" + ", ".join(VALID_BASEARCHES) + "). Default is %default.", default=DEFAULT_BASEARCH)
    parser.add_option("-a", "--all", default=False, action="store_true", help="Build tarballs for all dver,basearch combinations.")
    parser.add_option("--keep", default=False, action="store_true", help="Keep temp dirs after tarball creation")
    parser.add_option("--bundle", dest="bundles", action="append", default=[], help="Names of bundles (from {0}) to make tarballs for".format(BUNDLES_FILE))
    parser.add_option("--extra-repos", dest="extra_repos", action="append", help="Extra yum repos to use")

    options, args = parser.parse_args(argv[1:])

    if options.dver and options.dver not in VALID_DVERS:
        parser.error("--dver must be in " + ", ".join(VALID_DVERS))
    if options.basearch and options.basearch not in VALID_BASEARCHES:
        parser.error("--basearch must be in " + ", ".join(VALID_BASEARCHES))
    if not options.all and not options.dver:
        parser.error("Either --all or --dver must be specified.")

    if not options.bundles and not options.osgver:
        parser.error("--osgver or --bundle must be specified")

    if options.prerelease:
        options.extra_repos = options.extra_repos or []
        options.extra_repos.append('osg-prerelease-for-tarball')

    return (options, args)


def main(argv):
    prog_name = os.path.basename(argv[0])
    prog_dir = os.path.dirname(argv[0])

    options, args = parse_cmdline_args(argv)

    statusmsg("Checking privileges")
    if not check_running_as_root():
        return 1
    statusmsg("Checking required tools")
    if not check_tools():
        return 1
    statusmsg("Checking yum-priorities")
    if not check_yum_priorities():
        return 1

    bundlecfg = ConfigParser.RawConfigParser()
    with open(os.path.join(prog_dir, BUNDLES_FILE)) as bundlesfh:
        bundlecfg.readfp(bundlesfh)

    if options.bundles:
        bundles = options.bundles
    else:
        default_bundles_key = 'default_bundles_' + options.osgver
        if bundlecfg.has_option('GLOBAL', default_bundles_key):
            bundles = bundlecfg.get('GLOBAL', default_bundles_key).split(' ')
        else:
            errormsg("Option not found: section GLOBAL, key " + default_bundles_key)
            errormsg("No default set of bundles for osgver " + options.osgver)
            return 2

    if not bundles:
        errormsg("No bundles.  Exiting")
        return 1

    failed_paramsets = []
    written_tarballs = []
    for bundle in bundles:
        if options.all:
            paramsets = [tuple(x.split(',')) for x in bundlecfg.get(bundle, 'paramsets').split()]
        else:
            paramsets = [(options.dver, options.basearch)]

        for dver, basearch in paramsets:
            stage_dir_parent = tempfile.mkdtemp(prefix='stagedir-%s-%s-' % (dver, basearch))
            stage_dir = os.path.join(stage_dir_parent, bundlecfg.get(bundle, 'dirname'))

            statusmsg("Making stage 1 dir")

            repofile = get_repofile(prog_dir, bundlecfg, bundle, basearch=basearch, dver=dver)
            stage1_pkglist_file = os.path.join(prog_dir, bundlecfg.get(bundle, 'stage1file') % {'basearch': basearch, 'dver': dver})
            if not stage1.make_stage1_dir(stage_dir, repofile, dver, basearch, stage1_pkglist_file):
                errormsg("Making stage 1 dir unsuccessful. Files have been left in %r" % stage_dir)
                failed_paramsets.append([bundle, dver, basearch])
                continue

            stage2_pkglist = bundlecfg.get(bundle, 'packages').split()
            patch_dirs = []
            if bundlecfg.has_option(bundle, 'patchdirs'):
                patch_dirs = [os.path.join(prog_dir, x) for x in (bundlecfg.get(bundle, 'patchdirs') % {'basearch': basearch, 'dver': dver}).split()]

            (success, tarball_path, tarball_size) = \
                make_tarball(
                    bundlecfg=bundlecfg,
                    bundle=bundle,
                    basearch=basearch,
                    dver=dver,
                    packages=stage2_pkglist,
                    patch_dirs=patch_dirs,
                    prog_dir=prog_dir,
                    stage_dir=stage_dir,
                    relnum=options.relnum,
                    extra_repos=options.extra_repos,
                    version=options.version)

            if success:
                tarball_filecount = "?"
                try:
                    with os.popen("tar tzf %s | wc -l" % tarball_path) as ph:
                        tarball_filecount = int(to_str(ph.read()))
                except (EnvironmentError, ValueError) as e:
                    print("error getting file count: %s" % e)
                written_tarballs.append([tarball_path, tarball_size, tarball_filecount])
                print("Tarball created as %r, size %d bytes, %d files" % (tarball_path, tarball_size, tarball_filecount))
            else:
                failed_paramsets.append([bundle, dver, basearch])
                continue

            if not options.keep:
                statusmsg("Removing temp dirs")
                shutil.rmtree(stage_dir_parent, ignore_errors=True)
        #end for dver, basearch in paramsets
    #end for bundle in options.bundles

    if written_tarballs:
        statusmsg("The following tarballs were written:")
        for tarball in written_tarballs:
            print("    path: %-50s size: %9d bytes %5s files" % (tarball[0], tarball[1], tarball[2]))
    if failed_paramsets:
        errormsg("The following sets of parameters failed:")
        for paramset in failed_paramsets:
            print("    bundle: %-20s dver: %3s buildarch: %-6s" % (paramset[0], paramset[1], paramset[2]))
        return 1

    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv))

