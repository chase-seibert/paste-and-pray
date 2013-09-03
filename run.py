#!/usr/bin/env python

import argparse
import contextlib
import imp
import os
import platform
import sys
import tempfile
import time
import urllib

# dynamically loaded
sh = None


PROJECT_NAME = "advocoders"
PROJECT_GIT_REPO = "git@github.com:chase-seibert/advocoders.git"
HOST_NAMES = "advocoders.localhost.com"


@contextlib.contextmanager
def make_temp_directory():
    temp_dir = tempfile.mkdtemp()
    os.chdir(temp_dir)
    yield temp_dir


def get_options():
    home_dir = os.path.expanduser("~")
    working_directory = os.getcwd()
    return {
        "home_dir": home_dir,
        "working_directory": working_directory,
        "project_dir": os.path.join(home_dir, "projects", PROJECT_NAME),
    }


def load_this_script_deps():
    ''' This is tricky; we can't assume that pip or easy_install is already
    installed. Just download what you need manually and import it. '''
    global sh
    try:
        import sh as _sh
        sh = _sh
    except ImportError:
        urllib.urlretrieve("https://raw.github.com/amoffat/sh/master/sh.py", "sh.py")
        sh = imp.load_source("sh", "sh.py")


def get_os_and_version():
    if sys.platform == "darwin":
        return "osx", float('.'.join(platform.mac_ver()[0].split('.')[:2]))
    if sys.platform == "linux2":
        return "linux", None  # don't need anything version specific
    raise Exception("Unsupported OS: %s" % sys.platform)


def get_regular_username():
    ''' sudo preserves the orignal user in a env variable '''
    return os.environ.get('SUDO_USER')


def bash_config_file(options):
    _os = options.get('os')
    bash_profiles = {
        "linux": ".bashrc",
        "osx": ".bash_profile",
    }
    if _os in bash_profiles:
        return os.path.join(options.get("home_dir"), bash_profiles.get(_os))
    raise NotImplementedError()


def prepend_file(file_path, content):
    with file(file_path, 'r') as original:
        original_contents = original.read()
    with file(file_path, 'w') as modified:
        modified.write(content + '\n')
        modified.write(original_contents)


class InstallStep(object):

    root = False

    def __init__(self, options):

        self.options = options
        self.verbose_kwargs = {}

        if not self.options.get('quiet'):
            self.verbose_kwargs = dict(_out=sys.stdout, _err=sys.stdout)

        # for running commands as non-root user
        if self.root:
            self.sh = sh
        else:
            self.sh = sh.sudo.bake("-E", "-u", get_regular_username())

    def run_virtualenv(self, command, *args, **kwargs):
        ''' can't rely on sh.pip or sh.python to use the virtualenv version '''
        command_bin = sh.which(command)
        return sh.sudo("-E", "-u", get_regular_username(), command_bin, *args, **kwargs)

    @property
    def display_name(self):
        return self.__class__.__name__

    @property
    def display_doing(self):
        return self.__doc__.strip()

    @property
    def already_satisfied(self):
        return False

    def setup(self):
        raise NotImplementedError()

    def always_run(self):
        pass

    @property
    def display_troubleshooting(self):
        return None


class InstallStepAsRoot(InstallStep):
    root = True


class XCodeInstall(InstallStepAsRoot):
    ''' Downloading and installing XCode command line tools '''

    @property
    def already_satisfied(self):
        try:
            return len(self.sh.make("-version")) > 0
        except:
            return False

    def setup(self):
        version = self.options.get("version")
        # see: https://devimages.apple.com.edgekey.net/downloads/xcode/simulators/index-3905972D-B609-49CE-8D06-51ADC78E07BC.dvtdownloadableindex
        downloads = {
            10.7: "http://devimages.apple.com/downloads/xcode/command_line_tools_for_xcode_os_x_lion_april_2013.dmg",
            10.8: "http://devimages.apple.com/downloads/xcode/command_line_tools_for_xcode_os_x_mountain_lion_april_2013.dmg",
        }
        if version not in downloads:
            raise NotImplementedError("Could not locate XCode download for OSX %s" % version)
        download_file = downloads.get(version)
        # save this OUTSIDE the normal tmp dir; in case we need to restart install
        dmg_file = "/tmp/xcode.dmg"
        if not os.path.exists(dmg_file):
            urllib.urlretrieve(download_file, dmg_file)
        volume_dir = "/tmp/xcode"
        if not os.path.exists(volume_dir):
            self.sh.hdiutil("attach", "-mountpoint", volume_dir, dmg_file, **self.verbose_kwargs)
        mpkg_file = [f for f in os.listdir(volume_dir) if f.endswith(".mpkg")][0]
        try:
            self.sh.installer("-pkg", os.path.join(volume_dir, mpkg_file), "-target", "/", **self.verbose_kwargs)
        except sh.ErrorReturnCode as e:
            print e.stderr
        finally:
            self.sh.hdiutil("detach", volume_dir)

    @property
    def display_troubleshooting(self):
        return """
You can manually install the XCode Command Line Tools
by signing up for a free Apple ID and logging into
https://developer.apple.com/xcode/

Note: you don't need the full 2GB installer for Xcode;
the command line tools package is "only" 200MB.
"""


class HomebrewInstall(InstallStep):
    ''' Installing homebrew '''

    @property
    def already_satisfied(self):
        try:
            return len(self.sh.brew("--version")) > 0
        except:
            return False

    def setup(self):
        homebrew_fix = "homebrew_fix.rb"
        urllib.urlretrieve("https://gist.github.com/rpavlik/768518/raw/fix_homebrew.rb", homebrew_fix)
        self.sh.ruby(homebrew_fix, **self.verbose_kwargs)
        homebrew_source = "homebrew.rb"
        urllib.urlretrieve("https://raw.github.com/mxcl/homebrew/go", homebrew_source)
        self.sh.ruby(homebrew_source, **self.verbose_kwargs)

    @property
    def display_troubleshooting(self):
        return """
You can install homebrew manually by running this:

ruby -e "$(curl -fsSL https://raw.github.com/mxcl/homebrew/go)"
"""


class BrewDependenciesInstall(InstallStep):
    ''' Installing dependendies '''

    dependencies = [
        "libxml2",
        "libxslt",
        "libmagic",
        "postgresql",
        "libevent",
    ]

    @property
    def already_satisfied(self):
        installed = [i.strip() for i in self.sh.brew("list", "-1").split("\n") if i]
        not_installed = list(set(self.dependencies) - set(installed))
        return not_installed == []

    def setup(self):
        self.sh.brew("install", self.dependencies, **self.verbose_kwargs)

    @property
    def display_troubleshooting(self):
        return """
You can install the dependencies manually by running this:

brew install %s
""" % (' '.join(self.dependencies))


class VirtualEnvInstall(InstallStepAsRoot):
    ''' Installing pip and virtualenv '''

    @property
    def already_satisfied(self):
        try:
            return len(self.sh.virtualenv("--version")) > 0
        except:
            return False

    def setup(self):
        self.sh.easy_install("pip", **self.verbose_kwargs)
        self.sh.pip("install", "virtualenv", **self.verbose_kwargs)


class AptDependenciesInstall(InstallStepAsRoot):
    ''' Installing apt dependencies '''

    dependencies = [
        "libxml2-dev",
        "libxslt1-dev",
        "libmagic1",
        "python-virtualenv",
        "postgresql",
        "libpq-dev",
        "libevent-dev",
    ]

    @property
    def already_satisfied(self):
        return "0 upgraded, 0 newly installed" in self._run("--dry-run")

    def setup(self):
        self._run(**self.verbose_kwargs)

    def _run(self, flag="--yes", **kwargs):
        return self.sh.apt_get("install", flag, self.dependencies, **kwargs)

    @property
    def display_troubleshooting(self):
        return """
You can install the dependencies manually by running this:

sudo apt-get install --yes %s
""" % (' '.join(self.dependencies))


class UpdateHostsFile(InstallStepAsRoot):
    ''' Updating hosts file '''

    @property
    def already_satisfied(self):
        try:
            return self.sh.grep(sh.cat("/etc/hosts"), HOST_NAMES)
        except sh.ErrorReturnCode:
            return False

    def setup(self):
        prepend_file("/etc/hosts", "127.0.0.1 %s" % HOST_NAMES)

    @property
    def display_troubleshooting(self):
        return """
You can update your hosts file manually with:

sudo sh -c 'echo "127.0.0.1 %s" >> /etc/hosts'
""" % HOST_NAMES


class GitClone(InstallStep):
    ''' Cloning the project repo '''

    @property
    def already_satisfied(self):
        return os.path.exists(self.options.get("project_dir"))

    def setup(self):
        self.sh.git("clone", PROJECT_GIT_REPO, self.options.get("project_dir"))


class VirtualEnv(InstallStep):
    ''' Setting up a virtualenv and installing python dependencies '''

    def __init__(self, options):
        os.chdir(options.get("project_dir"))
        self.activate_this = os.path.join(options.get("project_dir"), 'virtualenv/bin/activate_this.py')
        self.requirements_file = os.path.join(options.get("project_dir"), "requirements.txt")
        super(VirtualEnv, self).__init__(options)

    @staticmethod
    def extract_pips(lines):
        return [line.split('==')[0].strip().lower() for line in lines]

    def pip(self, *args, **kwargs):
        return self.run_virtualenv("pip", *args, **kwargs)

    @property
    def already_satisfied(self):
        # this is the equivalent of source virtualenv/bin/activate, but
        # source is not usable via sh.py
        if not os.path.exists(self.activate_this):
            return False
        self.activate()
        items_installed = VirtualEnv.extract_pips(self.pip("freeze").split('\n'))
        items_required = VirtualEnv.extract_pips(open(self.requirements_file).readlines())
        items_diff = list(set(items_required) - set(items_installed))
        return not items_diff

    def activate(self):
        execfile(self.activate_this, dict(__file__=self.activate_this))

    def always_run(self):
        # want this to be activated for subsequent install steps
        if os.path.exists(self.activate_this):
            self.activate()

    def setup(self):
        if not os.path.exists(self.activate_this):
            self.sh.virtualenv("--no-site-packages", "--distribute", "virtualenv")
        self.activate()
        self.pip("install", "-r", self.requirements_file, **self.verbose_kwargs)


class SetEnvironmentVariable(InstallStep):

    variable = None
    value = None

    @property
    def display_doing(self):
        return "Setting the %s environment variable" % self.variable

    @property
    def already_satisfied(self):
        try:
            return self.sh.grep(sh.cat(bash_config_file(self.options)), self.variable)
        except sh.ErrorReturnCode:
            return False

    def always_run(self):
        os.environ[self.variable] = self.value

    def setup(self):
        prepend_file(bash_config_file(self.options), "export %s=%s" % (self.variable, self.value))


class ProductionEnvironmentVariable(SetEnvironmentVariable):
    variable = "PRODUCTION"
    value = "False"


class SetupDatabase(InstallStep):
    ''' Creating a local sqlite database '''

    @property
    def already_satisfied(self):
        return os.path.exists(os.path.join(options.get("project_dir"), "sqlite3.db"))

    def setup(self):
        os.chdir(self.options.get("project_dir"))
        self.run_virtualenv("python", "manage.py", "resetdb", **self.verbose_kwargs)


class RunServerAlias(InstallStep):
    ''' Creating the bash alias '''

    @property
    def already_satisfied(self):
        try:
            return self.sh.grep(sh.cat(bash_config_file(self.options)), 'runserver')
        except sh.ErrorReturnCode:
            return False

    def setup(self):
        alias = 'alias runserver="cd %s; source ../virtualenv/bin/activate; ./manage.py runserver 8001"' % (
            self.options.get("project_dir"))
        prepend_file(bash_config_file(self.options), alias)


class RunServer(InstallStep):
    ''' Running local development web server '''

    @property
    def already_satisfied(self):
        return True

    def _open(self, web_address):
        _os = self.options.get('os')
        open_commands = {
            "linux": "xdg-open",
            "osx": "open",
        }
        if _os in open_commands:
            getattr(self.sh, open_commands.get(_os))(web_address)

    def always_run(self):
        os.chdir(self.options.get("project_dir"))
        runserver = self.run_virtualenv("python", "manage.py", "runserver", "0:8001", _bg=True, _iter=True, _out=sys.stdout, _err=sys.stderr)
        server_address = "http://localhost:8001/"
        print """
===================================================

Congradulations! Your local development environment is successfully setup and live at %s.

Note: you can run the server directly in a NEW terminal by typing "runserver".

===================================================
""" % (server_address)

        time.sleep(3)
        self._open(server_address)
        try:
            runserver.wait()
        except KeyboardInterrupt:
            pass


def get_steps(_os, version):

    if _os == "osx":
        yield XCodeInstall
        yield HomebrewInstall
        yield BrewDependenciesInstall
        yield VirtualEnvInstall

    if _os == "linux":
        yield AptDependenciesInstall

    yield UpdateHostsFile
    yield GitClone
    yield VirtualEnv
    yield ProductionEnvironmentVariable
    yield SetupDatabase
    yield RunServerAlias
    yield RunServer


def run_steps(temp_dir, options):
    os_version_tuple = get_os_and_version()
    options['os'] = os_version_tuple[0]
    options['version'] = os_version_tuple[1]
    for step_cls in get_steps(*os_version_tuple):
        step = step_cls(options)
        step.always_run()
        if step.display_name in options.get('skip'):
            continue
        if step.already_satisfied and step.display_name not in options.get('force'):
            continue
        print '%s...' % step.display_doing
        try:
            step.setup()
        except sh.ErrorReturnCode as e:
            print e.stderr
        if step.display_name in options.get('force'):
            # when we force, we likely want to trouble-shoot just that step
            exit(1)
        if step.already_satisfied:
            continue
        print "ERROR: %s failed." % step.display_name
        if step.display_troubleshooting:
            print
            print "=================== Trouble-shooting ==================="
            print step.display_troubleshooting
        exit(1)


if __name__ == "__main__":
    # sudo -E python scripts/devlocal_setup.py
    parser = argparse.ArgumentParser(description='Automated devlocal setup')
    parser.add_argument('--force', default='', help='Run the specified steps again, comma separated.')
    parser.add_argument('--skip', default='', help='Skip the specified steps, comma separated.')
    parser.add_argument('--quiet', action="store_true", help='No verbose logging')
    args = parser.parse_args()
    options = get_options()
    options.update(vars(args))
    with make_temp_directory() as temp_dir:
        load_this_script_deps()  # must be in temp dir, downloads files
        sh.chmod("777", temp_dir)  # git clone needs to be able to swtich back
        run_steps(temp_dir, options)
