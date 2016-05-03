"""
Build all the conda recipes in the given directory sequentially if they do not
already exist on the given binstar channel.
Building is done in order of dependencies (circular dependencies are not supported).
Once a build is complete, the distribution will be uploaded (provided BINSTAR_TOKEN is
defined), and the next package will be processed.

"""
from __future__ import print_function

import logging
import os
import shutil
import subprocess
from argparse import Namespace

import binstar_client.utils
import binstar_client
from conda.api import get_index
from conda_build.metadata import MetaData
from conda_build.build import bldpkg_path
import conda.config

from . import inspect_binstar
from . import build


log = logging.getLogger('artefact_destination')


class ArtefactDestination(object):
    def __init__(self):
        pass

    def make_available(self, meta, built_dist_path, just_built):
        """
        Put the built distribution on this destination.

        Parameters
        ----------
        meta : MetaData
            The metadata of the thing to make available.
        built_dist_path
            The location of the built distribution for this artefact.
        just_built : bool
            Whether this artefact was just built, or was already available.

        """
        pass


class DirectoryDestination(ArtefactDestination):
    def __init__(self, directory):
        self.directory = os.path.abspath(os.path.expanduser(directory))
        if not os.path.exists(self.directory):
            os.makedirs(self.directory)
        if not os.path.isdir(self.directory):
            raise IOError("The destination provided is not a directory.")

    def make_available(self, meta, built_dist_path, just_built):
        if just_built:
            print(meta, built_dist_path, just_built)
            shutil.copy(built_dist_path, self.directory)


class AnacondaClientChannelDest(ArtefactDestination):
    def __init__(self, token, owner, channel, site=None):
        """
        token : str
            Token that will authenticate a user to the anaconda server
        owner : str
            The owner to upload a package to
        channel : str
            The channel to upload a package to
        site : str, optional
            The anaconda server URL to use.  No default, since None can be
            passed to the binstar_client creation which uses
            https://api.anaconda.org by default
        """
        self.token = token
        self.owner = owner
        self.channel = channel
        self._cli = None
        self.site = site

    @classmethod
    def from_spec(cls, spec, site=None):
        """
        Create an AnacondaClientChannelDest given the channel specification.

        Useful for command line arguments to be able to specify the owner
        and channel in a single string.

        Parameters
        ----------
        spec : str
            "owner/channel"
        site : str, optional
            The anaconda server URL to use.  No default, since None can be
            passed to the binstar_client creation which uses
            https://api.anaconda.org by default
        """
        token = os.environ.get("BINSTAR_TOKEN", None)
        if '/' in spec:
            owner, _, channel = spec.split('/')
        else:
            owner, channel = spec, 'main'
        return cls(token, owner, channel, site)

    def make_available(self, meta, built_dist_path, just_built):
        if self._cli is None:
            self._cli = binstar_client.utils.get_binstar(
                Namespace(token=self.token, site=self.site))

        already_with_owner = inspect_binstar.distribution_exists(self._cli, self.owner, meta)
        already_on_channel = inspect_binstar.distribution_exists_on_channel(self._cli,
                                                                            self.owner,
                                                                            meta,
                                                                            channel=self.channel)
        if already_on_channel and not just_built:
            log.info('Nothing to be done for {} - it is already on {}/{}.'.format(meta.name(), self.owner, self.channel))
        elif already_on_channel and just_built:
            # We've just built, and the owner already has a distribution on this channel.
            log.warn("Assuming the distribution we've just built and the one on {}/{} are the same.".format(self.owner, self.channel))

        elif already_with_owner:
            if just_built:
                log.warn("Assuming the distribution we've just built and the one owned by {} are the same.".format(self.owner))
            # Link a distribution.
            log.info('Adding existing {} to the {}/{} channel.'.format(meta.dist(), self.owner, self.channel))
            inspect_binstar.add_distribution_to_channel(self._cli, self.owner, meta, channel=self.channel)

        elif just_built:
            # Upload the distribution
            log.info('Uploading {} to the {} channel.'.format(meta.name(), self.channel))
            build.upload(self._cli, meta, self.owner, channels=[self.channel])

        elif not just_built:
            # The distribution already existed, but not under the target owner.
            if 'http://' in built_dist_path or 'https://' in built_dist_path:
                raise NotImplementedError('cross owner copying not yet implemented.')
