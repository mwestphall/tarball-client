#!/usr/bin/env python
import glob
import os
import shutil
import subprocess
import tempfile
import types
import ConfigParser


class YumConfig(object):
    def __init__(self, dver, basearch):
        if not dver in ['el5', 'el6']:
            raise ValueError('Invalid dver, should be el5 or el6')
        if not basearch in ['i386', 'x86_64']:
            raise ValueError('Invalid basearch, should be i386 or x86_64')
        self.dver = dver
        self.basearch = basearch
        self.config = ConfigParser.RawConfigParser()
        self.set_main()
        self.add_repos()
        self.conf_file = tempfile.NamedTemporaryFile(suffix='.conf')
        self.write_config(self.conf_file.file)


    def __del__(self):
        try:
            self.conf_file.close()
        except (AttributeError, NameError):
            pass


    def set_main(self):
        self.config.read(['/etc/yum.conf'])
        self.config.remove_option('main', 'distroverpkg')
        self.config.set('main', 'plugins', '1')


    def add_repos(self):
        sec = 'osg-release-build'
        self.config.add_section(sec)
        self.config.set(sec, 'name', '%s-osg-release-build latest (%s)' % (self.dver, self.basearch))
        self.config.set(sec, 'baseurl', 'http://koji-hub.batlab.org/mnt/koji/repos/%s-osg-release-build/latest/%s/' % (self.dver, self.basearch))
        self.config.set(sec, 'failovermethod', 'priority')
        self.config.set(sec, 'priority', '98')
        self.config.set(sec, 'enabled', '1')
        self.config.set(sec, 'gpgcheck', '0')

        sec2 = 'osg-minefield-limited'
        self.config.add_section(sec2)
        self.config.set(sec2, 'name', '%s-osg-development latest (%s) (limited)' % (self.dver, self.basearch))
        self.config.set(sec2, 'baseurl', 'http://koji-hub.batlab.org/mnt/koji/repos/%s-osg-development/latest/%s/' % (self.dver, self.basearch))
        self.config.set(sec2, 'failovermethod', 'priority')
        self.config.set(sec2, 'priority', '97')
        self.config.set(sec2, 'enabled', '1')
        self.config.set(sec2, 'gpgcheck', '0')
        self.config.set(sec2, 'includepkgs', 'osg-ca-scripts')


    def write_config(self, dest_file):
        close_dest_fileobj_at_end = False
        if type(dest_file) is types.StringType:
            dest_fileobj = open(dest_file, 'w')
            close_dest_fileobj_at_end = True
        elif type(dest_file) is types.IntType:
            dest_fileobj = os.fdopen(dest_file, 'w')
        elif type(dest_file) is types.FileType:
            dest_fileobj = dest_file
        else:
            raise TypeError("dest_file is not something that can be used as a file"
                "(must be a path, a file descriptor, or a file object)")

        self.config.write(dest_fileobj)
        dest_fileobj.flush()
        if close_dest_fileobj_at_end:
            dest_fileobj.close()


    def yum_clean(self):
        args = ["-c", self.conf_file.name, "--enablerepo=*"]
        subprocess.call(["yum", "clean", "all"] + args)
        subprocess.call(["yum", "clean", "expire-cache"] + args)


    def install(self, installroot, packages):
        if not installroot:
            raise ValueError("'installroot' empty")
        if not packages:
            raise ValueError("'packages' empty")
        if type(packages) is types.StringType:
            packages = [packages]

        cmd = ["yum", "install",
               "-y",
               "--installroot", installroot,
               "-c", self.conf_file.name,
               "-d1",
               "--disablerepo=*",
               "--enablerepo=osg-release-build",
               "--enablerepo=osg-minefield-limited",
               "--nogpgcheck"]
        cmd += packages
        return subprocess.call(cmd)


    def fake_install(self, installroot, packages):
        if not installroot:
            raise ValueError("'installroot' empty")
        if not packages:
            raise ValueError("'packages' empty")
        if type(packages) is types.StringType:
            packages = [packages]

        rpm_dir = tempfile.mkdtemp(suffix='.fake-install')
        try:
            cmd = ["yumdownloader",
                   "--destdir", rpm_dir,
                   "--resolve",
                   "--installroot", installroot,
                   "-c", self.conf_file.name,
                   "-d1",
                   "--disablerepo=*",
                   "--enablerepo=osg-release-build",
                   "--enablerepo=osg-minefield-limited",
                   "--nogpgcheck"]
            cmd += packages
            # FIXME Better EC and exceptions
            err = subprocess.call(cmd)
            if err:
                return err
            rpms = glob.glob(os.path.join(rpm_dir, "*.rpm"))
            cmd2 = ["rpm",
                    "--install",
                    "--verbose",
                    "--justdb",
                    "--root", installroot]
            cmd2 += rpms
            return subprocess.call(cmd2)
        finally:
            shutil.rmtree(rpm_dir, ignore_errors=True)


