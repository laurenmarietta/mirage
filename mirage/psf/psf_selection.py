#! /usr/bin/env python

from ast import literal_eval
from glob import glob
import os

from astropy.io import fits
import numpy as np
#from photutils.utils import ShepardIDWInterpolator as idw
from photutils import FittableImageModel
from scipy.interpolate import interp2d, RectBivariateSpline
from webbpsf.utils import to_griddedpsfmodel


def get_gridded_psf_library(instrument, detector, filtername, pupilname, width, oversamp,
                            number_of_psfs, wavefront_error, wavefront_error_group, library_path):
    """
    Find the filename for the appropriate gridded PSF library and read it in
    """
    library_file = get_library_file(instrument, detector, filtername, pupilname, width,
                                    oversamp, number_of_psfs, wavefront_error,
                                    wavefront_error_group, library_path)
    print(library_file)

    try:
        library = to_griddedpsfmodel(library_file)
    except OSError:
        print("OSError: Unable to open {}.".format(library_file))
    return library


def get_library_file(instrument, detector, filt, pupil, fov_pix, oversample, num_psf, wfe,
                     wfe_group, library_path):
        """Given an instrument and filter name along with the path of
        the PSF library, find the appropriate library file to load.

        Parameters:
        -----------
        instrument : str
            Name of instrument the PSFs are from

        detector : str
            Name of the detector within ```instrument```

        filt : str
            Name of filter used for PSF library creation

        pupil : str
            Name of pupil wheel element used for PSF library creation

        fov_pix : int
            With of the PSF stamps in units of nominal pixels

        oversample : int
            Oversampling factor of the PSF stamps. (e.g oversamp=2 means
            NIRCam SW PSFs of 0.031 / 2 arcsec per pixel)

        num_psf : int
            Number of PSFs across the detector in the library. (e.g. for
            a 3x3 library of PSFs, num_psf=9)

        wfe : str
            Wavefront error. Can be 'predicted' or 'requirements'

        wfe_group : int
            Wavefront error realization group. Must be an integer from 0 - 9.

        library_path : str
            Path pointing to the location of the PSF library

        Returns:
        --------
        lib_file : str
            Name of the PSF library file for the instrument and filtername
        """
        filename = '{}_{}_{}_{}_fovp{}_samp{}_npsf{}_wfe_{}_wfegroup{}.fits'.format(instrument.lower(),
                                                                                   detector.lower(),
                                                                                   filt.lower(),
                                                                                   pupil.lower(),
                                                                                   fov_pix, oversample,
                                                                                   num_psf, wfe, wfe_group)
        print('PSF file to use: {}'.format(filename))
        lib_file = os.path.join(library_path, filename)

        # If no matching files are found, or more than 1 matching file is
        # found, raise an error.
        if not os.path.isfile:
            raise FileNotFoundError("PSF library file {} does not exist."
                                    .format(lib_file))
        return lib_file


def get_library_file_new(instrument, detector, filt, pupil, wfe, wfe_group, library_path):
    """
    """
    psf_files = glob(os.path.join(library_path, '*wfegroup0.fits'))

    # Create a dictionary of header information for all PSF library files
    psf_table = {}
    matches = []
    for filename in psf_files:
        header = fits.getheader(filename)
        file_inst = header['INSTRUME'].lower()
        file_det = header['DETECTOR'].upper()
        file_filt = header['FILTER'].upper()
        #file_pupil = header['PUPIL'].upper()
        file_pupil = 'CLEAR'
        print('PUPIL VALUE SET TO CLEAR WHILE AWAITING KEYWORD')
        opd = header['PUPILOPD']
        if 'requirements' in opd:
            file_wfe = 'requirements'
        elif 'predicted' in opd:
            file_wfe = 'predicted'
        #file_wfe_grp = header['']
        file_wfe_grp = 0
        print('WFE REALIZATION SET TO ZERO WHILE WAITING FOR KEYWORD')
        match = (file_inst == instrument and file_det == detector and file_filt == filt and
                 file_pupil == pupil and file_wfe == wfe and file_wfe_grp == wfe_group)
        print(filename, file_inst, file_det, file_filt, file_pupil, file_wfe, file_wfe_grp)
        if match:
            matches.append(filename)
        psf_table[filename] = [file_inst, file_det, file_filt, file_pupil, file_wfe, file_wfe_grp, match]

    # Find files matching the requested inputs
    if len(matches) == 1:
        return matches[0]
    elif len(matches) == 0:
        raise ValueError("No PSF library file found matching requested parameters.")
    elif len(matches) > 1:
        raise ValueError("More than one PSF library file matches requested parameters: {}".format(matches))









class PSFCollection:
    """Class to contain a PSF library across a single detector for a
    single filter. Through interpolation, the PSF at any location on
    the detector can be created."""

    def __init__(self, instrument, detector, filtername, pupilname, width, oversamp,
                 number_of_psfs, wavefront_error, wavefront_error_group, library_path):
        """Upon instantiation of the class, read in the PSF library
        contained in the given fits file. Also pull out relevant
        information such as the oversampling factor and the locations
        on the detector of the fiducial PSFs. This assumes the PSF
        library file is in the format created by ```Mirage's```
        ```CreatePSFLibrary``` class in psf_library.py.

        Parameters:
        -----------
        library_file : str
            Name of a fits file containing the PSF library.

        Returns:
        --------
        None
        """
        library_file = self.get_library_file(instrument, detector, filtername, pupilname, width,
                                             oversamp, number_of_psfs, wavefront_error,
                                             wavefront_error_group, library_path)

        try:
            self.library = to_griddedpsfmodel(library_file)
        except OSError:
            print("OSError: Unable to open {}.".format(library_file))

        # Get some basic information about the library
        self.psf_y_dim, self.psf_x_dim = self.library.data.shape[-2:]
        self.psf_x_dim /= self.library.oversampling
        self.psf_y_dim /= self.library.oversampling
        self.num_psfs = len(self.library.grid_xypos)
        #self.x_det = []
        #self.y_det = []
        #self.x_index = []
        #self.y_index = []
        #for num in range(self.num_psfs):
        #    yval, xval = literal_eval(self.library_info['DET_YX' + str(num)])
        #    self.x_det.append(xval)
        #    self.y_det.append(yval)
        #    yi, xi = literal_eval(self.library_info['DET_JI' + str(num)])
        #    self.x_index.append(xi)
        #    self.y_index.append(yi)
        #if self.num_psfs > 1:
        #    self.interpolator = self.create_interpolator()
        #else:
        #    self.interpolator = None

    def create_interpolator(self, interp_type='interp2d'):
        """Create an interpolator function for the detector-dependent
        PSF position. Need a separate interpolator function for each pixel?

        Parameters:
        -----------
        interp_type: str
            Can be 'interp2d' or 'idw'

        pass self.x_det as xloc, or just use the class variable??

        Returns:
        --------
        """
        # Get the locations on the detector for each PSF
        # in the library

        # Have data of dimension xpsf, ypsf at locations x_det, y_det
        # psfydim = self.library_info['NAXIS2']
        # psfxdim = self.library_info['NAXIS1']
        # x_psf = np.arange(psfxdim)
        # y_psf = np.arange(psfydim)

        # Create interpolator for each pixel
        if interp_type.lower() == 'interp2d':
            interpolator = self.make_interp2d_functions(self.x_det,
                                                        self.y_det,
                                                        self.library)
        elif interp_type.lower() == 'idw':
            interpolator = None
        else:
            raise ValueError(("interp_type of {} not supported."
                              .format(interp_type)))
        return interpolator

    def evaluate_interp2d(self, splines, xout, yout):
        """Evaluate the splines produced in make_interp2d_functions for each
        pixel in the PSF given a location on the detector

        Parameters:
        -----------
        splines : list
            List of lists of splines. Output from make_interp2d_functions

        xout : int
            x coordinate on detector at which to evaluate

        yout : int
            y coordinate on detector at which to evaluate

        Returns:
        --------
        psf : numpy.ndarray
            2D array containing the interpolated PSF
        """
        xlen = len(splines[0])
        ylen = len(splines)
        psf = np.zeros((ylen, xlen))
        for y, rowlist in enumerate(splines):
            for x, spline in enumerate(rowlist):
                pix = spline(xout, yout)
                psf[y, x] = pix
        return psf

    def find_nearest_neighbors(self, x_out, y_out, num_nearest):
        """Determine the location of the num_nearest nearest reference PSFs
        to a given location on the detector.

        Parameters:
        -----------
        x_out : int
            x-coordinate on the detector to find distances from

        y_out : int
            y-coordinate on the detector to find distances from

        num_nearest : int
            Number of nearest reference PSFs to find

        Returns:
        --------
        match_indexes : list
            List containing 4 tuples; one for each of the 4 nearest
            reference PSFs. Each tuple contains (index of x_psfs,y_psfs
            list, radial distance to x_out,yout)
        """
        x_psfs = np.array(self.x_det)
        y_psfs = np.array(self.y_det)
        distances = np.sqrt(np.abs(x_psfs - x_out)**2 +
                            np.abs(y_psfs - y_out)**2)
        ranking = np.argsort(distances)

        # If the requested PSF position falls exactly on the location
        # of one of the reference PSFs, then use just that single PSF
        # with a weight of 1.0
        if min(distances) == 0:
            num_nearest = 1

        x_loc_index = np.array(self.x_index)
        y_loc_index = np.array(self.y_index)
        match_index = ranking[0:num_nearest]
        x_nearest = x_loc_index[match_index]
        y_nearest = y_loc_index[match_index]
        result = (x_nearest, y_nearest, distances[match_index])
        return result

    def get_library_file(self, instrument, filt, pupil, fov_pix, oversample, num_psf, wfe,
                         wfe_group, library_path):
        """Given an instrument and filter name along with the path of
        the PSF library, find the appropriate library file to load.

        Parameters:
        -----------
        instrument : str
            Name of instrument the PSFs are from

        detector : str
            Name of the detector within ```instrument```

        filt : str
            Name of filter used for PSF library creation

        pupil : str
            Name of pupil wheel element used for PSF library creation

        fov_pix : int
            With of the PSF stamps in units of nominal pixels

        oversample : int
            Oversampling factor of the PSF stamps. (e.g oversamp=2 means
            NIRCam SW PSFs of 0.031 / 2 arcsec per pixel)

        num_psf : int
            Number of PSFs across the detector in the library. (e.g. for
            a 3x3 library of PSFs, num_psf=9)

        wfe : str
            Wavefront error. Can be 'predicted' or 'requirements'

        wfe_group : int
            Wavefront error realization group. Must be an integer from 0 - 9.

        library_path : str
            Path pointing to the location of the PSF library

        Returns:
        --------
        lib_file : str
            Name of the PSF library file for the instrument and filtername
        """
        filename = '{}_{}_{}_{}_fov{}_samp{}_npsf{}_wfe_{}_wfegroup{}.fits'.format(instrument.lower(),
                                                                                    detector.lower(),
                                                                                    filt.lower(),
                                                                                    pupil.lower(),
                                                                                    fov_pix, oversample,
                                                                                    num_psf, wfe, wfe_group)
        lib_file = os.path.join(library_path, filename)

        # If no matching files are found, or more than 1 matching file is
        # found, raise an error.
        if not os.path.isfile:
            raise FileNotFoundError("PSF library file {} does not exist."
                                    .format(lib_file))
        return lib_file[0]

    def make_interp2d_functions(self, xpos, ypos, psfdata):
        """Create a list of lists containing splines for each pixel in the PSF
        image. Note that this assumes a regular grid of locations for the
        reference PSFs. (e.g. Assume np.unique creates an input x list of
        [0, 680, 1365, 2047], and a y list with the same values, then it is
        expected that there are 16 PSFs in the libaray at locations
        corresponding to all combinations of the values in the x and y lists.

        Parameters:
        -----------
        xpos : list
            X coordinate on the detector corresponding to each PSF

        ypos : list
            Y coordinate on the detector corresponding to each PSF

        psfdata : numpy.ndarray
            PSF library. 4D array with dimensions (x loc on detector, y loc on
            detector, x PSF size, y PSF size)

        Returns:
        --------
        interp_functions : list
            List of lists containing the spline for each pixel in the PSF
        """
        xs = np.unique(xpos)
        ys = np.unique(ypos)
        interp_functions = []
        loc_ydim, loc_xdim, psf_ydim, psf_xdim = psfdata.shape

        # Need to loop over the pixels and produce an interpolating function
        # for each.
        for ypix in range(psf_ydim):
            xlist = []
            for xpix in range(psf_xdim):
                pixeldata = self.library[:, :, ypix, xpix]
                # interp2d_fncn = interp2d(xs, ys, pixeldata, kind='linear')
                interp2d_fncn = RectBivariateSpline(xs, ys, pixeldata, kx=1, ky=1)
                xlist.append(interp2d_fncn)
            interp_functions.append(xlist)
        return interp_functions

    def minimal_psf_evaluation(self, model, deltax=0., deltay=0.):
        """
        Create a PSF by evaluating a FittableImageModel instance. Return
        an array only just big enough to contain the PSF data.

         Parameters:
        -----------
        model : obj
            FittableImageModel instance containing the PSF model

        deltax : float
            Offset in the x-direction, in units of nominal pixels, to
            shift the interpolated PSF within the output (interpolated)
            frame.

        deltay : float
            Offset in the y-direction, in units of nominal pixels, to
            shift the interpolated PSF within the output (interpolated)
            frame.

         Returns:
        --------
        eval_psf : ndarray
            2D numpy array containing the evaluated PSF, with normalized signal
        """
        eval_xshape = np.int(np.ceil(model.shape[1] / model.oversampling))
        eval_yshape = np.int(np.ceil(model.shape[0] / model.oversampling))
        y, x = np.mgrid[0:eval_yshape, 0:eval_xshape]
        eval_psf = model.evaluate(x=x, y=y, flux=1.,
                                  x_0=(eval_xshape - 1) / 2 + deltax,
                                  y_0=(eval_yshape - 1) / 2 + deltay)
        return eval_psf

    def populate_epsfmodel(self, psf_data):
        """Create an instance of EPSFModel and populate the data
        from the given fits file. Also populate information
        about the oversampling rate.

        Parameters:
        -----------
        psf_data : numpy.ndarray
            Numpy array containing the 2d image of a PSF

        Returns:
        --------
        psf : obj
            FittableImageModel instance
        """
        # Normalize
        psf_data /= np.sum(psf_data)

        # Create instance. Assume the PSF is centered
        # in the array
        oversample = self.library_info['OVERSAMP']
        psf = FittableImageModel(psf_data, oversampling=oversample)
        # psf = EPSFModel(psf_data, oversampling=oversample)
        return psf

    def position_interpolation(self, x, y, method="spline", idw_number_nearest=4, idw_alpha=-2):
        """Interpolate the PSF library to construct the PSF at a
        a given location on the detector. Note that the coordinate system used
        in this case has (0.0, 0.0) centered in the lower left pixel. (0.5, 0.5)
        corresponds to the upper right corner of that pixel, and (-0.5, -0.5) the
        lower left corner. This is important more for when the FittableImageModel
        that is returned here is evaluated.

        Parameters
        ----------
        x :  int (float?)
            X-coordinate value for the new PSF

        y : int (float?)
            Y-coordinate value for the new PSF

        method : str
            Type of interpolation to use

        idw_number_nearest : int
            For weighted averaging (method='idw'), the number of nearest
            reference PSFs to the location of the interpolated PSF to use
            when calculating the weighted average. Default = 4.

        idw_alpha : float
            Exponent used for turning distances into weights. Default is -2.

        Returns
        -------
        out : FittableImageModel
            Instance of FittableImageModel containing the interpolated PSF
        """
        # Get the locations on the detector for each PSF
        # in the library
        if self.num_psfs == 1:
            interp_psf = self.library[0, 0, :, :]
        else:
            if method == "spline":
                interp_psf = self.evaluate_interp2d(self.interpolator, x, y)
            elif method == "idw":
                nearest_x, nearest_y, nearest_dist = self.find_nearest_neighbors(x, y, idw_number_nearest)
                if len(nearest_dist) > 1:
                    psfs_to_avg = self.library[nearest_x, nearest_y, :, :]
                    interp_psf = self.weighted_avg(psfs_to_avg, nearest_dist,
                                                   idw_alpha)
                elif len(nearest_dist) == 1:
                    interp_psf = self.library[nearest_x, nearest_y, :, :]
            else:
                raise ValueError(("{} interpolation method not supported."
                                .format(method)))

        # Return resulting PSF in instance of FittableImageModel (or EPSFModel)
        return self.populate_epsfmodel(interp_psf)

    def select_detector(self, det_name, input_file):
        """Given a PSF library, select only the PSFs associated with a
        given detector.





        NOT NEEDED ANYMORE









        Parameters:
        -----------
        det_name : str
            Name of the detector whose PSFs are to be returned.

        input_file : str
            Name of the file containing the PSF library. Only used for
            printing error messages.

        Returns:
        --------
        match : int
            Index number indicating which slice of self.library corresponds
            to the given detector
        """
        det_list = []
        for i in range(self.library_info['NAXIS5']):
            det_list.append(self.library_info['DETNAME' + str(i)])

        if det_name in det_list:
            match = np.where(np.array(det_list) == det_name)[0][0]
            return match
        else:
            raise ValueError(("No PSFs for detector {} in {}."
                              .format(det_name, input_file)))

    def weighted_avg(self, psfs, distances, alpha):
        """Calculate the weighted average of the input PSFs given their distances
        to the location of interest on the detector

        Parameters:
        -----------
        psfs : numpy.ndarray
            Array containing the PSFs to be used to calculate the weighted
            average. 3D array

        distances : list
            List of radial distances from the location of interest to the PSFs
            in psfs

        alpha : float
            Exponent to use in determining weights. weights = distance**alpha
            Should be between -2 and 0.

        Returns:
        --------
        avg_psf : numpy.ndarray
            Array containing the weighted average PSF
        """
        alpha = np.float(alpha)
        weights = distances**alpha
        output = np.average(psfs, axis=0, weights=weights)
        return output
