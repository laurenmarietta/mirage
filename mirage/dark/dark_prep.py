#! /usr/bin/env python

'''
Module for preparing a given dark current exposure for
integration with a ramp of simulated sources created
using (e.g.) catalog_seed_image.py.

Authors:
--------

    - Bryan Hilbert, Kevin Volk

Use:
----

    This module can be imported as such:

    ::

        from mirage.dark.dark_prep import DarkPrep
        dark = DarkPrep()
        dark.paramfile = 'my_parameters.yaml'
        dark.prepare()
'''

import sys
import os
import argparse
from math import floor

import yaml
import pkg_resources
import numpy as np
from astropy.io import fits, ascii

from ..utils import read_fits, utils, siaf_interface

# Allowed instruments
INST_LIST = ['nircam', 'niriss', 'fgs']


class DarkPrep():

    def __init__(self):
        # Locate the module files, so that we know where to look
        # for config subdirectory
        self.modpath = pkg_resources.resource_filename('mirage', '')

        # Get the location of the MIRAGE_DATA environment
        # variable, so we know where to look for darks, CR,
        # PSF files, etc later
        self.env_var = 'MIRAGE_DATA'
        datadir = os.environ.get(self.env_var)
        if datadir is None:
            raise ValueError(("WARNING: {} environment variable is not set."
                              "This must be set to the base directory"
                              "containing the darks, cosmic ray, PSF, etc"
                              "input files needed for the simulation."
                              "These files must be downloaded separately"
                              "from the Mirage package.".format(self.env_var)))

    def check_params(self):
        """Check for acceptible values for the input parameters in the
        yaml file.
        """
        # Check instrument name
        if self.params['Inst']['instrument'].lower() not in INST_LIST:
            raise ValueError(("WARNING: {} instrument not implemented within "
                              "simulator".format(self.params['Inst']['instrument'])))

        # If user requests not to use the pipeline,
        # make sure the input is a linearized dark, and not
        # a raw dark
        if self.params['Inst']['use_JWST_pipeline'] is False:
            if self.params['Reffiles']['linearized_darkfile'] is None:
                raise ValueError(("WARNING: You specified no use of the JWST pipeline, but "
                                  "have not provided a linearized dark file to use. Without the "
                                  "pipeline, a raw dark cannot be used."))

        # Make sure nframe, nskip, ngroup are all integers
        try:
            self.params['Readout']['nframe'] = int(self.params['Readout']['nframe'])
        except ValueError:
            print("WARNING: Input value of nframe is not an integer.")

        try:
            self.params['Readout']['nskip'] = int(self.params['Readout']['nskip'])
        except ValueError:
            print("WARNING: Input value of nskip is not an integer.")

        try:
            self.params['Readout']['ngroup'] = int(self.params['Readout']['ngroup'])
        except ValueError:
            print("WARNING: Input value of ngroup is not an integer.")

        try:
            self.params['Readout']['nint'] = int(self.params['Readout']['nint'])
        except ValueError:
            print("WARNING: Input value of nint is not an integer.")

        # Make sure that the requested number of groups is
        # less than or equal to the maximum allowed. If you're
        # continuing on with an unknown readout pattern (not
        # recommended) then assume a max of 10 groups.
        # For science operations, ngroup is going to be limited
        # to 10 for all readout patterns except for the DEEP
        # patterns, which can go to 20. (FOR FULL FRAME!!)
        # Subarray exposures can use more!!
        match = self.readpatterns['name'] == self.params['Readout']['readpatt'].upper()
        if sum(match) == 1:
            maxgroups = self.readpatterns['maxgroups'].data[match][0]
        if sum(match) == 0:
            print(("Unrecognized readout pattern {}. Assuming a maximum allowed number of groups of 10."
                   .format(self.params['Readout']['readpatt'])))
            maxgroups = 10

        if (self.params['Readout']['ngroup'] > maxgroups):
            print(("WARNING: {} is limited to a maximum of {} groups. Proceeding with ngroup = {}."
                   .format(self.params['Readout']['readpatt'], maxgroups, maxgroups)))
            self.params['Readout']['readpatt'] = maxgroups

        # Check for entries in the parameter file that are None or blank,
        # indicating the step should be skipped. Create a dictionary of steps
        # and populate with True or False
        self.runStep = {}
        # self.runStep['linearity'] = self.check_run_step(self.params['Reffiles']['linearity'])
        self.runStep['badpixmask'] = self.check_run_step(self.params['Reffiles']['badpixmask'])
        self.runStep['linearized_darkfile'] = self.check_run_step(self.params['Reffiles']['linearized_darkfile'])
        self.runStep['saturation_lin_limit'] = self.check_run_step(self.params['Reffiles']['saturation'])
        self.runStep['superbias'] = self.check_run_step(self.params['Reffiles']['superbias'])
        self.runStep['linearity'] = self.check_run_step(self.params['Reffiles']['linearity'])

        # If the pipeline is going to be used to create
        # the linearized dark current ramp, make sure the
        # specified configuration files are present.
        if not self.runStep['linearized_darkfile']:
            dqcheck = self.check_run_step(self.params['newRamp']['dq_configfile'])
            if not dqcheck:
                raise FileNotFoundError(("WARNING: DQ pipeline step configuration file not provided. "
                                         "This file is needed to run the pipeline."))
            satcheck = self.check_run_step(self.params['newRamp']['sat_configfile'])
            if not satcheck:
                raise FileNotFoundError(("WARNING: Saturation pipeline step configuration file not provided. "
                                         "This file is needed to run the pipeline."))
            sbcheck = self.check_run_step(self.params['newRamp']['superbias_configfile'])
            if not sbcheck:
                raise FileNotFoundError(("WARNING: Superbias pipeline step configuration file not provided. "
                                        "This file is needed to run the pipeline."))
            refpixcheck = self.check_run_step(self.params['newRamp']['refpix_configfile'])
            if not refpixcheck:
                raise FileNotFoundError(("WARNING: Refpix pipeline step configuration file not provided. "
                                         "This file is needed to run the pipeline."))
            lincheck = self.check_run_step(self.params['newRamp']['linear_configfile'])
            if not lincheck:
                raise FileNotFoundError(("WARNING: Linearity pipeline step configuration file not provided. "
                                         "This file is needed to run the pipeline."))

    def check_run_step(self, filename):
        """Check to see if a filename exists in the parameter file
        or if it is set to none.

        Parameters
        ----------
        filename : str
            Name of the entry in the yaml file

        Returns
        -------
        state : bool
            True if entry is a filename, False if it is non or empty
        """
        if ((len(filename) == 0) or (filename.lower() == 'none')):
            return False
        else:
            return True

    def crop_dark(self, model):
        """Cut the dark current array down to the size dictated
        by the subarray bounds

        Parameters
        ----------
        model : obj
            read_fits object holding dark current as well as superbias and refpix signal

        Returns
        -------
        model : obj
            read_fits object with cropped data arrays
        """
        modshape = model.data.shape
        yd = modshape[-2]
        xd = modshape[-1]

        if ((self.subarray_bounds[0] != 0) or (self.subarray_bounds[2] != (xd - 1))
           or (self.subarray_bounds[1] != 0) or (self.subarray_bounds[3] != (yd - 1))):

            if len(modshape) == 4:
                model.data = model.data[:, :, self.subarray_bounds[1]:self.subarray_bounds[3] + 1,
                                        self.subarray_bounds[0]:self.subarray_bounds[2] + 1]
                try:
                    model.sbAndRefpix = model.sbAndRefpix[:, :, self.subarray_bounds[1]:
                                                          self.subarray_bounds[3] + 1,
                                                          self.subarray_bounds[0]:self.subarray_bounds[2] + 1]
                except:
                    pass
                try:
                    model.zeroframe = model.zeroframe[:, self.subarray_bounds[1]:
                                                      self.subarray_bounds[3] + 1,
                                                      self.subarray_bounds[0]:self.subarray_bounds[2] + 1]
                except:
                    pass
            if len(modshape) == 3:
                model.data = model.data[:, self.subarray_bounds[1]:self.subarray_bounds[3] + 1,
                                        self.subarray_bounds[0]:self.subarray_bounds[2] + 1]
                try:
                    model.sbAndRefpix = model.sbAndRefpix[:, self.subarray_bounds[1]:
                                                          self.subarray_bounds[3] + 1,
                                                          self.subarray_bounds[0]:self.subarray_bounds[2] + 1]
                except:
                    pass
                try:
                    model.zeroframe = model.zeroframe[:, self.subarray_bounds[1]:
                                                      self.subarray_bounds[3] + 1,
                                                      self.subarray_bounds[0]:self.subarray_bounds[2] + 1]
                except:
                    pass
            elif len(modshape) == 2:
                model.data = model.data[self.subarray_bounds[1]:self.subarray_bounds[3] + 1,
                                        self.subarray_bounds[0]:self.subarray_bounds[2] + 1]
                try:
                    model.sbAndRefpix = model.sbAndRefpix[self.subarray_bounds[1]:self.subarray_bounds[3] + 1,
                                                          self.subarray_bounds[0]:self.subarray_bounds[2] + 1]
                except:
                    pass
                try:
                    model.zeroframe = model.zeroframe[self.subarray_bounds[1]:
                                                      self.subarray_bounds[3] + 1,
                                                      self.subarray_bounds[0]:self.subarray_bounds[2] + 1]
                except:
                    pass

        # Make sure that if the output is supposedly a
        # 4-amplifier file, that the number of
        # pixels in the x direction is a multiple of 4.
        nfast = self.subarray_bounds[2] - self.subarray_bounds[0] + 1
        nslow = self.subarray_bounds[3] - self.subarray_bounds[1] + 1
        nramp = (self.params['Readout']['nframe'] + self.params['Readout']['nskip']) * \
            self.params['Readout']['ngroup']

        if self.params['Readout']['namp'] != 4 and self.params['Readout']['namp'] != 1:
            raise ValueError(('ERROR: amplifier mode specified ({}) is not allowed'
                              .format(self.params['Readout']['namp'])))

        if self.params['Readout']['namp'] == 4:
            n = int(nfast / 4) * 4
            if n != nfast:
                raise ValueError(("ERROR: 4 amplifier mode specified but the number of pixels "
                                  "in the fast read direction ({}) is not a multiple of 4."
                                  .format(nfast)))
        return model

    def darkints(self):
        """Check the number of integrations in the dark
        current file and compare with the requested
        number of integrations. Add/remove integrations
        if necessary

        Parameters
        ----------

        None


        Returns
        -------

        None
        """
        ndarkints, ngroups, ny, nx = self.dark.data.shape
        reqints = self.params['Readout']['nint']

        if reqints <= ndarkints:
            # Fewer requested integrations than are in the
            # input dark.
            print("{} output integrations requested.".format(reqints))
            self.dark.data = self.dark.data[0:reqints, :, :, :]
            if self.dark.sbAndRefpix is not None:
                self.dark.sbAndRefpix = self.dark.sbAndRefpix[0:reqints, :, :, :]
            if self.dark.zeroframe is not None:
                self.dark.zeroframe = self.dark.zeroframe[0:reqints, :, :]

        elif reqints > ndarkints:
            # More requested integrations than are in input dark.
            print(('Requested output has {} integrations, while input dark has only {}.'
                   .format(reqints, ndarkints)))
            print('Adding integrations to input dark by making copies of the input.')
            self.integration_copy(reqints, ndarkints)

    def data_volume_check(self, obj):
        """Make sure that the input integration has
        enough frames/groups to create the requested
        number of frames/groups of the output

        Parameters
        ----------
        obj : obj
            Instance of read_fits class containing dark current data and other info

        Returns
        -------
        None
        """
        ngroup = int(self.params['Readout']['ngroup'])
        nframe = int(self.params['Readout']['nframe'])
        nskip = int(self.params['Readout']['nskip'])

        inputframes = obj.data.shape[1]
        if ngroup * (nskip + nframe) > inputframes:
            print(("WARNING: Not enough frames in the input integration to "
                   "create the requested number of output groups. Input has "
                   "{} frames. Requested output is {} groups each created from "
                   "{} frames plus skipping {} frames between groups for a total "
                   "of {} frames."
                   .format(inputframes, ngroup, nframe, nskip, ngroup * (nframe + nskip))))
            print(("Making copies of {} dark current frames and adding them to "
                   "the end of the dark current integration."
                   .format(ngroup * (nskip + nframe) - inputframes)))

            # Figure out how many more frames we need,
            # in terms of how many copies of the original dark
            div = floor((ngroup * (nskip + nframe)) / inputframes)
            mod = (ngroup * (nskip + nframe)) % inputframes

            # If more frames are needed than there are frames
            # in the original dark, then make copies of the
            # entire thing as many times as necessary, adding
            # the signal from the previous final frame to each.
            for ints in range(div - 1):
                extra_frames = np.copy(obj.data)
                obj.data = np.hstack((obj.data, extra_frames + obj.data[:, -1, :, :]))
                if obj.sbAndRefpix is not None:
                    extra_sb = np.copy(obj.sbAndRefpix)
                    obj.sbAndRefpix = np.hstack((obj.sbAndRefpix, extra_sb + obj.sbAndRefpix[:, -1, :, :]))

            # At this point, if more frames are needed, but fewer
            # than an entire copy of self.dark.data, then add the
            # appropriate number of frames here.
            extra_frames = np.copy(obj.data[:, 1:mod + 1, :, :]) - obj.data[:, 0, :, :]
            obj.data = np.hstack((obj.data, extra_frames + obj.data[:, -1, :, :]))
            if obj.sbAndRefpix is not None:
                extra_sb = np.copy(obj.sbAndRefpix[:, 1:mod + 1, :, :]) - obj.sbAndRefpix[:, 0, :, :]
                obj.sbAndRefpix = np.hstack((obj.sbAndRefpix, extra_sb + obj.sbAndRefpix[:, -1, :, :]))

        elif ngroup * (nskip + nframe) < inputframes:
            # If there are more frames in the dark than we'll need,
            # crop the extras in order to reduce memory use
            obj.data = obj.data[:, 0:ngroup * (nskip + nframe), :, :]
            if obj.sbAndRefpix is not None:
                obj.sbAndRefpix = obj.sbAndRefpix[:, 0:ngroup * (nskip + nframe), :, :]
        obj.header['NGROUPS'] = ngroup * (nskip + nframe)

    def filecheck(self):
        """Make sure the requested input files exist
        or reference files, assume first that they are located in
        the directory tree under the datadir (from the MIRAGE_DATA
        environment variable). If not, assume the input is a full path
        and check there.
        """
        rlist = [['Reffiles', 'dark'],
                 ['Reffiles', 'linearized_darkfile'],
                 ['Reffiles', 'superbias'],
                 ['Reffiles', 'linearity'],
                 ['Reffiles', 'saturation']]
        for ref in rlist:
            self.ref_check(ref)

    def full_paths(self):
        """Expand all input paths to be full paths
        This is to allow for easier Condor-ization of
        many runs"""
        pathdict = {'Reffiles': ['dark', 'linearized_darkfile',
                                 'superbias', 'subarray_defs', 'readpattdefs',
                                 'linearity', 'saturation', 'gain', 'pixelflat',
                                 'illumflat', 'astrometric', 'badpixmask',
                                 'ipc', 'crosstalk',
                                 'occult', 'pixelAreaMap'],
                    'cosmicRay': ['path'],
                    'simSignals': ['pointsource', 'psfpath', 'galaxyListFile',
                                   'extended', 'movingTargetList',
                                   'movingTargetSersic',
                                   'movingTargetExtended',
                                   'movingTargetToTrack'],
                    'newRamp': ['dq_configfile', 'sat_configfile',
                                'superbias_configfile', 'refpix_configfile',
                                'linear_configfile'],
                    'Output': ['file', 'directory']}

        all_config_files = {'nircam': {'Reffiles-readpattdefs': 'nircam_read_pattern_definitions.list',
                                       'Reffiles-subarray_defs': 'NIRCam_subarray_definitions.list',
                                       'Reffiles-crosstalk': 'xtalk20150303g0.errorcut.txt',
                                       'newRamp-dq_configfile': 'dq_init.cfg',
                                       'newRamp-sat_configfile': 'saturation.cfg',
                                       'newRamp-superbias_configfile': 'superbias.cfg',
                                       'newRamp-refpix_configfile': 'refpix.cfg',
                                       'newRamp-linear_configfile': 'linearity.cfg'},
                            'niriss': {'Reffiles-readpattdefs': 'niriss_readout_pattern.txt',
                                       'Reffiles-subarray_defs': 'niriss_subarrays.list',
                                       'Reffiles-crosstalk': 'niriss_xtalk_zeros.txt',
                                       'newRamp-dq_configfile': 'dq_init.cfg',
                                       'newRamp-sat_configfile': 'saturation.cfg',
                                       'newRamp-superbias_configfile': 'superbias.cfg',
                                       'newRamp-refpix_configfile': 'refpix.cfg',
                                       'newRamp-linear_configfile': 'linearity.cfg'},
                            'fgs': {'Reffiles-readpattdefs': 'guider_readout_pattern.txt',
                                    'Reffiles-subarray_defs': 'guider_subarrays.list',
                                    'Reffiles-crosstalk': 'guider_xtalk_zeros.txt',
                                    'newRamp-dq_configfile': 'dq_init.cfg',
                                    'newRamp-sat_configfile': 'saturation.cfg',
                                    'newRamp-superbias_configfile': 'superbias.cfg',
                                    'newRamp-refpix_configfile': 'refpix.cfg',
                                    'newRamp-linear_configfile': 'linearity.cfg'}}
        config_files = all_config_files[self.params['Inst']['instrument'].lower()]

        for key1 in pathdict:
            for key2 in pathdict[key1]:
                if self.params[key1][key2].lower() not in ['none', 'config']:
                    self.params[key1][key2] = os.path.abspath(os.path.expandvars(self.params[key1][key2]))
                elif self.params[key1][key2].lower() == 'config':
                    cfile = config_files['{}-{}'.format(key1, key2)]
                    fpath = os.path.join(self.modpath, 'config', cfile)
                    self.params[key1][key2] = fpath
                    print("'config' specified: Using {} for {}:{} input file".format(fpath, key1, key2))

    def get_base_dark(self):
        """Read in the dark current ramp that will serve as the
        base for the simulated ramp"""

        # First make sure that the file exists
        local = os.path.isfile(self.params['Reffiles']['dark'])
        # Future improvement: download a missing dark file
        if not local:
            try:
                print("Local copy of dark current file")
                print("{} not found.".format(self.params['Reffiles']['dark']))
                print("Downloading.")
                darkfile = os.path.split(self.params['Reffiles']['dark'])[1]
                hh = fits.open(os.path.join(self.dark_url, darkfile))
                hh.writeto(self.params['Reffiles']['dark'])
            except Exception:
                print("Local copy of dark current file")
                print("{} not found.".format(self.params['Reffiles']['dark']))
                print("And unable to download. Quitting.")

        self.dark = read_fits.Read_fits()
        self.dark.file = self.params['Reffiles']['dark']

        # Depending on the method indicated in the input file
        # read in the dark using astropy or RampModel
        if self.params['Inst']['use_JWST_pipeline']:
            self.dark.read_datamodel()

            try:
                # Remove non-pipeline related keywords
                # (e.g. CV3 temps/voltages)
                self.dark.__delattr__('extra_fits')
            except:
                pass

        else:
            self.dark.read_astropy()

        # We assume that the input dark current integration is raw, which means
        # the data are in the original ADU measured by the detector. So the
        #  data range should be no larger than 65536
        darkrange = 1.*self.dark.data.max() - 1.*self.dark.data.min()
        if darkrange > 65535.:
            raise ValueError(("WARNING: Range of data values in the input dark is too large. "
                              "We assume the input dark is raw ADU values, with a range no more than 65536."))

        # If the inputs are signed integers, change to unsigned.
        if self.dark.data.min() < 0.:
            self.dark.data += 32768

        # If the input is any readout pattern other than RAPID, then
        # make sure that the output readout patten matches. Only RAPID
        # can be averaged and transformed into another readout pattern
        if self.dark.header['READPATT'] not in ['RAPID', 'NISRAPID', 'FGSRAPID']:
            if self.params['Readout']['readpatt'].upper() != self.dark.header['READPATT']:
                print(("WARNING: cannot transform input {} integration into "
                       "output {} integration.".format(self.dark.header['READPATT'],
                                                       self.params['Readout']['readpatt'])))
                raise ValueError(("Only RAPID, NISRAPID, or FGSRAPID inputs can be translated to a "
                                  "different readout pattern"))
        else:
            pass

        # Finally, collect information about the detector, which will be needed for astrometry later
        self.detector = self.dark.header['DETECTOR']
        self.instrument = self.dark.header['INSTRUME']
        self.fastaxis = self.dark.header['FASTAXIS']
        self.slowaxis = self.dark.header['SLOWAXIS']

    def integration_copy(self, req, darkint):
        """Use copies of integrations in the dark current input to
        make up integrations in the case where the output has
        more integrations than the input

        Parameters
        ----------
        req : int
            Requested number of dark current integrations for the output

        darkint : int
            Number of integrations in the input dark current exposure

        Returns
        -------
        None
        """

        ncopies = np.int((req - darkint) / darkint)
        extras = (req - darkint) % darkint

        # Full copies of the dark exposure (all integrations)
        if ncopies > 0:
            copydata = self.dark.data
            if self.dark.sbAndRefpix is not None:
                copysb = self.dark.sbAndRefpix
            if self.dark.zeroframe is not None:
                copyzero = self.dark.zeroframe
            for i in range(ncopies):
                self.dark.data = np.vstack((self.dark.data, copydata))
                if self.dark.sbAndRefpix is not None:
                    self.dark.sbAndRefpix = np.vstack((self.dark.sbAndRefpix, copysb))
                if self.dark.zeroframe is not None:
                    self.dark.zeroframe = np.vstack((self.dark.zeroframe, copyzero))

        # Partial copy of dark (some integrations)
        if extras > 0:
            self.dark.data = np.vstack((self.dark.data, self.dark.data[0:extras, :, :, :]))
            if self.dark.sbAndRefpix is not None:
                self.dark.sbAndRefpix = np.vstack((self.dark.sbAndRefpix,
                                                   self.dark.sbAndRefpix[0:extras, :, :, :]))
            if self.dark.zeroframe is not None:
                self.dark.zeroframe = np.vstack((self.dark.zeroframe, self.dark.zeroframe[0:extras, :, :]))

        self.dark.header['NINTS'] = req

    def linearize_dark(self, darkobj):
        """Beginning with the input dark current ramp, run the dq_init, saturation, superbias
        subtraction, refpix and nonlin pipeline steps in order to produce a linearized
        version of the ramp. This will be used when combining the dark ramp with the
        simulated signal ramp.

        Parameters
        -----------
        darkobj : obj
            Instance of read_fits class containing dark current data and info

        Returns
        -------
        linDarkObj : obj
            Modified read_fits instance with linearized dark current data
        """
        from jwst.dq_init import DQInitStep
        from jwst.saturation import SaturationStep
        from jwst.superbias import SuperBiasStep
        from jwst.refpix import RefPixStep
        from jwst.linearity import LinearityStep

        # First we need to place the read_fits object into a RampModel instance
        if self.runStep['linearized_darkfile']:
            subfile = self.params['Reffiles']['linearized_darkfile']
        else:
            subfile = self.params['Reffiles']['dark']
        dark = darkobj.insert_into_datamodel(subfile)

        print('Creating a linearized version of the dark current input ramp')
        print('using JWST calibration pipeline.')

        # Run the DQ_Init step
        if self.runStep['badpixmask']:
            linDark = DQInitStep.call(dark,
                                      config_file=self.params['newRamp']['dq_configfile'],
                                      override_mask=self.params['Reffiles']['badpixmask'])
        else:
            linDark = DQInitStep.call(dark, config_file=self.params['newRamp']['dq_configfile'])

        # If the saturation map is provided, use it. If not, default to whatever is in CRDS
        if self.runStep['saturation_lin_limit']:
            linDark = SaturationStep.call(linDark,
                                          config_file=self.params['newRamp']['sat_configfile'],
                                          override_saturation=self.params['Reffiles']['saturation'])
        else:
            linDark = SaturationStep.call(linDark,
                                          config_file=self.params['newRamp']['sat_configfile'])

        # If the superbias file is provided, use it. If not, default to whatever is in CRDS
        if self.runStep['superbias']:
            linDark = SuperBiasStep.call(linDark,
                                         config_file=self.params['newRamp']['superbias_configfile'],
                                         override_superbias=self.params['Reffiles']['superbias'])
        else:
            linDark = SuperBiasStep.call(linDark,
                                         config_file=self.params['newRamp']['superbias_configfile'])

        # Reference pixel correction
        linDark = RefPixStep.call(linDark,
                                  config_file=self.params['newRamp']['refpix_configfile'])

        # Save a copy of the superbias- and reference pixel-subtracted
        # dark. This will be used later to add these effects back in
        # after the synthetic signals have been added and the non-linearity
        # effects are added back in when using the PROPER combine method.
        sbAndRefpixEffects = dark.data - linDark.data

        # Linearity correction - save the output so that you won't need to
        # re-run the pipeline when using the same dark current file in the
        # future. Use the linearity coefficient file if provided
        base_name = self.params['Output']['file'].split('/')[-1]
        linearoutfile = base_name[0:-5] + '_linearized_dark_current_ramp.fits'
        linearoutfile = os.path.join(self.params['Output']['directory'], linearoutfile)
        if self.runStep['linearity']:
            linDark = LinearityStep.call(linDark,
                                         config_file=self.params['newRamp']['linear_configfile'],
                                         override_linearity=self.params['Reffiles']['linearity'],
                                         output_file=linearoutfile)
        else:
            linDark = LinearityStep.call(linDark,
                                         config_file=self.params['newRamp']['linear_configfile'],
                                         output_file=linearoutfile)

        print(("Linearized dark (output directly from pipeline saved as {}"
               .format(linearoutfile)))

        # Now we need to put the data back into a read_fits object
        linDarkobj = read_fits.Read_fits()
        linDarkobj.model = linDark
        linDarkobj.rampmodel_to_obj()
        linDarkobj.sbAndRefpix = sbAndRefpixEffects

        return linDarkobj

    def prepare(self):
        """MAIN FUNCTION"""

        # Read in the yaml parameter file
        self.read_parameter_file()

        # Expand locations to be full path names
        self.full_paths()
        self.filecheck()

        # Base name for output files
        base_name = self.params['Output']['file'].split('/')[-1]
        self.basename = os.path.join(self.params['Output']['directory'],
                                     base_name[0:-5])

        # Check the entered read pattern info
        self.readpattern_check()

        # Check input parameters for any bad values
        self.check_params()

        # Read in the subarray definition file
        self.subdict = utils.read_subarray_definition_file(self.params['Reffiles']['subarray_defs'])
        self.params = utils.get_subarray_info(self.params, self.subdict)

        # Get the subarray boundaries from pysiaf
        siaf_inst = self.params['Inst']['instrument']
        instrument_siaf = siaf_interface.get_instance(siaf_inst)
        self.siaf = instrument_siaf[self.params['Readout']['array_name']]
        junk0, junk1, self.ffsize, \
            self.subarray_bounds = siaf_interface.get_siaf_information(instrument_siaf,
                                                                       self.params['Readout']['array_name'],
                                                                       0.0, 0.0,
                                                                       self.params['Telescope']['rotation'])
        # Read in the input dark current frame
        if not self.runStep['linearized_darkfile']:
            self.get_base_dark()
            self.linDark = None
        else:
            self.read_linear_dark()
            self.dark = self.linDark

        # Make sure there is enough data (frames/groups)
        # in the input integration to produce
        # the proposed output integration
        self.data_volume_check(self.dark)

        # Compare the requested number of integrations
        # to the number of integrations in the input dark
        print("Dark shape as read in: {}".format(self.dark.data.shape))
        self.darkints()
        print("Dark shape after copying integrations to match request: {}".format(self.dark.data.shape))

        # Put the input dark (or linearized dark) into the
        # requested readout pattern
        self.dark, sbzeroframe = self.reorder_dark(self.dark)
        print(('DARK has been reordered to {} to match the input readpattern of {}'
               .format(self.dark.data.shape, self.dark.header['READPATT'])))

        # If a raw dark was read in, create linearized version
        # here using the SSB pipeline. Better to do this
        # on the full dark before cropping, so that reference
        # pixels can be used in the processing.
        if ((self.params['Inst']['use_JWST_pipeline']) & (self.runStep['linearized_darkfile'] is False)):

            # Linear ize the dark ramp via the SSB pipeline.
            # Also save a diff image of the original dark minus
            # the superbias and refpix subtracted dark, to use later.

            # In order to linearize the dark, the JWST pipeline must
            # be present, and self.dark will have to be translated back
            # into a RampModel instance
            # print('Working on {}'.format(self.dark))
            self.linDark = self.linearize_dark(self.dark)
            print("Linearized dark shape: {}".format(self.linDark.data.shape))

            if self.params['Readout']['readpatt'].upper() in ['RAPID', 'NISRAPID', 'FGSRAPID']:
                print(("Output is {}, grabbing zero frame from linearized dark"
                       .format(self.params['Readout']['readpatt'].upper())))
                self.zeroModel = read_fits.Read_fits()
                self.zeroModel.data = self.linDark.data[:, 0, :, :]
                self.zeroModel.sbAndRefpix = self.linDark.sbAndRefpix[:, 0, :, :]
            elif ((self.params['Readout']['readpatt'].upper() not in ['RAPID', 'NISRAPID', 'FGSRAPID']) &
                  (self.dark.zeroframe is not None)):
                print("Now we need to linearize the zeroframe because the")
                print("output readpattern is not RAPID, NISRAPID, or FGSRAPID")
                # Now we need to linearize the zeroframe. Place it
                # into a RampModel instance before running the
                # pipeline steps
                self.zeroModel = read_fits.Read_fits()
                self.zeroModel.data = np.expand_dims(self.dark.zeroframe, axis=1)
                self.zeroModel.header = self.linDark.header
                self.zeroModel.header['NGROUPS'] = 1
                self.zeroModel = self.linearize_dark(self.zeroModel)
                # Return the zeroModel data to 3 dimensions
                # integrations, y, x
                self.zeroModel.data = self.zeroModel.data[:, 0, :, :]
                self.zeroModel.sbAndRefpix = self.zeroModel.sbAndRefpix[:, 0, :, :]
                # In this case the zeroframe has changed from what
                # was read in. So let's remove the original zeroframe
                # to avoid confusion
                self.linDark.zeroframe = np.zeros(self.linDark.zeroframe.shape)
            else:
                self.zeroModel = None

            # Now crop self.linDark, self.dark, and zeroModel
            # to requested subarray
            self.dark = self.crop_dark(self.dark)
            self.linDark = self.crop_dark(self.linDark)

            if self.zeroModel is not None:
                self.zeroModel = self.crop_dark(self.zeroModel)

        elif self.runStep['linearized_darkfile']:
            # If no pipeline is run
            self.zeroModel = read_fits.Read_fits()
            self.zeroModel.data = self.dark.zeroframe
            self.zeroModel.sbAndRefpix = sbzeroframe

            # Crop the linearized dark to the requested
            # subarray size
            # THIS WILL CROP self.dark AS WELL SINCE
            # self.linDark IS JUST A REFERENCE IN THE NON
            # PIPELINE CASE!!
            self.linDark = self.crop_dark(self.linDark)
            if self.zeroModel.data is not None:
                self.zeroModel = self.crop_dark(self.zeroModel)
        else:
            raise NotImplementedError(("Mode not yet supported! Must use either: use_JWST_pipeline "
                                       "= True and a raw or linearized dark or supply a linearized dark. "
                                       "Cannot yet skip the pipeline and provide a raw dark."))

        # Save the linearized dark
        # if self.params['Output']['save_intermediates']:
        h0 = fits.PrimaryHDU()
        h1 = fits.ImageHDU(self.linDark.data, name='SCI')
        h2 = fits.ImageHDU(self.linDark.sbAndRefpix, name='SBANDREFPIX')
        h3 = fits.ImageHDU(self.zeroModel.data, name='ZEROFRAME')
        h4 = fits.ImageHDU(self.zeroModel.sbAndRefpix, name='ZEROSBANDREFPIX')

        # Populate basic info in the 0th extension header
        nints, ngroups, yd, xd = self.linDark.data.shape
        h0.header['READPATT'] = self.params['Readout']['readpatt'].upper()
        h0.header['NINTS'] = nints
        h0.header['NGROUPS'] = ngroups
        h0.header['NFRAMES'] = self.params['Readout']['nframe']
        h0.header['NSKIP'] = self.params['Readout']['nskip']
        h0.header['DETECTOR'] = self.detector
        h0.header['INSTRUME'] = self.instrument
        h0.header['SLOWAXIS'] = self.slowaxis
        h0.header['FASTAXIS'] = self.fastaxis

        hl = fits.HDUList([h0, h1, h2, h3, h4])
        objname = self.basename + '_linear_dark_prep_object.fits'
        objname = os.path.join(self.params['Output']['directory'], objname)
        hl.writeto(objname, overwrite=True)
        print(("Linearized dark frame plus superbias and reference"
               "pixel signals, as well as zeroframe, saved to {}. "
               "This can be used as input to the observation"
               "generator.".format(objname)))

        # important variables
        # self.linDark
        # self.zeroModel
        # Make a read_fits instance that contains all the important
        # information, for ease in connecting with next step of the
        # simulator
        self.prepDark = read_fits.Read_fits()
        self.prepDark.data = self.linDark.data
        self.prepDark.zeroframe = self.zeroModel.data
        self.prepDark.sbAndRefpix = self.linDark.sbAndRefpix
        self.prepDark.zero_sbAndRefpix = self.zeroModel.sbAndRefpix
        self.prepDark.header = self.linDark.header

    def read_linear_dark(self):
        """Read in the linearized version of the dark current ramp
        using the read_fits class"""
        try:
            print(('Reading in linearized dark current ramp from {}'
                   .format(self.params['Reffiles']['linearized_darkfile'])))
            self.linDark = read_fits.Read_fits()
            self.linDark.file = self.params['Reffiles']['linearized_darkfile']
            self.linDark.read_astropy()
        except:
            raise IOError('WARNING: Unable to read in linearized dark ramp.')

        # Finally, collect information about the detector, which will be needed for astrometry later
        self.detector = self.linDark.header['DETECTOR']
        self.instrument = self.linDark.header['INSTRUME']
        self.fastaxis = self.linDark.header['FASTAXIS']
        self.slowaxis = self.linDark.header['SLOWAXIS']

    def read_parameter_file(self):
        """Read in the yaml parameter file"""
        try:
            with open(self.paramfile, 'r') as infile:
                self.params = yaml.load(infile)
        except FileNotFoundError:
            print("WARNING: unable to open {}".format(self.paramfile))

    def readpattern_check(self):
        """Check the readout pattern that's entered and set the number of averaged frames
        as well as the number of skipped frames per group"""
        self.params['Readout']['readpatt'] = self.params['Readout']['readpatt'].upper()

        # Read in readout pattern definition file
        # and make sure the possible readout patterns are in upper case
        self.readpatterns = ascii.read(self.params['Reffiles']['readpattdefs'])
        self.readpatterns['name'] = [s.upper() for s in self.readpatterns['name']]

        # If the requested readout pattern is in the table of options,
        # then adopt the appropriate nframe and nskip
        if self.params['Readout']['readpatt'] in self.readpatterns['name']:
            mtch = self.params['Readout']['readpatt'] == self.readpatterns['name']
            self.params['Readout']['nframe'] = self.readpatterns['nframe'][mtch].data[0]
            self.params['Readout']['nskip'] = self.readpatterns['nskip'][mtch].data[0]
            print(('Requested readout pattern {} is valid. '
                  'Using the nframe = {} and nskip = {}'
                   .format(self.params['Readout']['readpatt'],
                           self.params['Readout']['nframe'],
                           self.params['Readout']['nskip'])))
        else:
            # If the read pattern is not present in the definition file
            # then quit.
            raise ValueError(("WARNING: the {} readout pattern is not defined in {}."
                              .format(self.params['Readout']['readpatt'],
                                      self.params['Reffiles']['readpattdefs'])))

    def ref_check(self, rele):
        """Check for the existence of the input reference file
        Assume first that the file is in the directory tree
        specified by the MIRAGE_DATA environment variable.

        Parameters
        ----------
        rele : tup
            Keywords needed to access a given entry in self.params from the
            input yaml file

        Returns
        -------
        None
        """
        rfile = self.params[rele[0]][rele[1]]
        if rfile.lower() != 'none':
            c1 = os.path.isfile(rfile)
            if not c1:
                raise FileNotFoundError(("WARNING: Unable to locate the {}, {} "
                                         "input file! Not present in {}"
                                         .format(rele[0], rele[1], rfile)))

    def reorder_dark(self, dark):
        """Reorder the input dark ramp using the requested
        readout pattern (nframe, nskip). If the initial
        dark ramp is RAPID, NISRAPID, or FGSRAPID, then save and return
        the 0th frame.

        Parameters
        ----------
        dark : obj
            Instance of read_fits class containing dark current data and info

        Returns
        -------
        dark : obj
            Instance of read_fits class where dark data have been reordered to match
            the requested readout pattern

        sbzero : numpy.ndarray
            Zeroth frame data from the dark current data. This is saved separately
            because averaging for non-RAPID readout patterns will destroy the frame
        """
        if self.params['Reffiles']['linearized_darkfile']:
            datatype = np.float
        else:
            datatype = np.int32

        # Get the info for the dark integration
        darkpatt = dark.header['READPATT']
        dark_nframe = dark.header['NFRAMES']
        mtch = self.readpatterns['name'].data == darkpatt
        dark_nskip = self.readpatterns['nskip'].data[mtch][0]

        nint, ngroup, yd, xd = dark.data.shape
        outdark = np.zeros((self.params['Readout']['nint'], self.params['Readout']['ngroup'], yd, xd))

        if dark.sbAndRefpix is not None:
            outsb = np.zeros((self.params['Readout']['nint'], self.params['Readout']['ngroup'], yd, xd))

        # We can only keep a zero frame around if the input dark
        # is RAPID, NISRAPID, or FGSRAPID. Otherwise that information is lost.
        darkzero = None
        sbzero = None
        rapids = ['RAPID', 'NISRAPID', 'FGSRAPID']
        if ((darkpatt in rapids) & (dark.zeroframe is None)):
            dark.zeroframe = dark.data[:, 0, :, :]
            print("Saving 0th frame from data to the zeroframe extension")
            if dark.sbAndRefpix is not None:
                sbzero = dark.sbAndRefpix[:, 0, :, :]
        elif ((darkpatt not in rapids) & (dark.zeroframe is None)):
            print("Unable to save the zeroth frame because the input dark current ramp is not RAPID.")
            sbzero = None
        elif ((darkpatt in rapids) & (dark.zeroframe is not None)):
            # In this case we already have the zeroframe
            if dark.sbAndRefpix is not None:
                sbzero = dark.sbAndRefpix[:, 0, :, :]
        elif ((darkpatt not in rapids) & (dark.zeroframe is not None)):
            # Non RAPID dark, zeroframe is present, but
            # we can't get sbAndRefpix for the zeroth frame
            # because the pattern is not RAPID.
            sbzero = None

        # We have already guaranteed that either the readpatterns match
        # or the dark is RAPID, so no need to worry about checking for
        # other cases here.

        if ((darkpatt in rapids) and (self.params['Readout']['readpatt'] not in rapids)):

            framesPerGroup = self.params['Readout']['nframe'] + self.params['Readout']['nskip']
            accumimage = np.zeros_like(outdark[0, 0, :, :], dtype=datatype)

            if dark.sbAndRefpix is not None:
                zeroaccumimage = np.zeros_like(outdark[0, 0, :, :], dtype=np.float)

            # Loop over integrations
            for integ in range(self.params['Readout']['nint']):
                frames = np.arange(0, self.params['Readout']['nframe'])

                # Loop over groups
                for i in range(self.params['Readout']['ngroup']):
                    # Average together the appropriate frames,
                    # skip the appropriate frames
                    print(("Averaging dark current ramp. Frames {}, to become "
                           "group {}".format(frames, i)))

                    # If averaging needs to be done
                    if self.params['Readout']['nframe'] > 1:
                        accumimage = np.mean(dark.data[integ, frames, :, :], axis=0)
                        if dark.sbAndRefpix is not None:
                            zeroaccumimage = np.mean(dark.sbAndRefpix[integ, frames, :, :], axis=0)

                        # If no averaging needs to be done
                    else:
                        accumimage = dark.data[integ, frames[0], :, :]
                        if dark.sbAndRefpix is not None:
                            zeroaccumimage = dark.sbAndRefpix[integ, frames[0], :, :]

                    outdark[integ, i, :, :] += accumimage
                    if dark.sbAndRefpix is not None:
                        outsb[integ, i, :, :] += zeroaccumimage

                    # Increment the frame indexes
                    frames = frames + framesPerGroup

        elif (self.params['Readout']['readpatt'] == darkpatt):
            # If the input dark is not RAPID, or if the readout
            # pattern of the input dark and
            # the output ramp match, then no averaging needs to
            # be done
            outdark = dark.data[:, 0:self.params['Readout']['ngroup'], :, :]
            if dark.sbAndRefpix is not None:
                outsb = dark.sbAndRefpix[:, 0:self.params['Readout']['ngroup'], :, :]
        else:
            # This check should already have been done,
            # but just to be sure...
            raise ValueError(("WARNING: dark current readout pattern is {} and requested "
                              "output is {}. Cannot convert between the two."
                              .format(darkpatt, self.params['Readout']['readpatt'])))

        # Now place the reorganized dark into the data object and
        # update the appropriate metadata
        dark.data = outdark
        if dark.sbAndRefpix is not None:
            dark.sbAndRefpix = outsb
        dark.header['READPATT'] = self.params['Readout']['readpatt']
        dark.header['NFRAMES'] = self.params['Readout']['nframe']
        dark.header['NSKIP'] = self.params['Readout']['nskip']
        dark.header['NGROUPS'] = self.params['Readout']['ngroup']
        dark.header['NINTS'] = self.params['Readout']['nint']

        return dark, sbzero

    def add_options(self, parser=None, usage=None):
        if parser is None:
            parser = argparse.ArgumentParser(usage=usage, description='Simulate JWST ramp')
        parser.add_argument("paramfile", help=("File describing the input parameters and instrument "
                                               "settings to use. (YAML format)."))
        return parser


if __name__ == '__main__':

    usagestring = 'USAGE: dark_prep.py inputs.yaml'

    indark = DarkPrep()
    parser = indark.add_options(usage=usagestring)
    args = parser.parse_args(namespace=indark)
    indark.prepare()
