'''Define unit tests for parsing APT templates with pytest.

Authors
-------
    - Lauren Chambers

Use
---
    Ensure you have pytest installed. Then, simply run pytest in any
    parent directory of nircam_simulator/tests/:
    >>> pytest
'''

import os
import glob
import yaml

from lxml import etree
import pytest

from mirage.scripts import write_observationlist, yaml_generator, utils, apt_inputs

# to be set before running test
# os.environ['MIRAGE_DATA'] = ''

PROPOSAL_ID = '1111'
APT_NAMESPACE = '{http://www.stsci.edu/JWST/APT}'

TESTS_DIR = os.path.realpath(os.path.join(os.getcwd(), os.path.dirname(__file__)))


def RunAllAPTTemplates(instrument):
    '''Parse the given APT files and create a set of .yamls for a given
    instrument
    '''
    # Define .pointing and .xml file locations
    pointing_file = os.path.join(TESTS_DIR, 'test_data', instrument, instrument + 'Test.pointing')
    xml_file = os.path.join(TESTS_DIR, 'test_data',  instrument, instrument + 'Test.xml')

    # Open XML file, get element tree of the APT proposal to determine how
    # many observations there are
    with open(xml_file) as f:
        tree = etree.parse(f)
    observation_data = tree.find(APT_NAMESPACE + 'DataRequests')
    obs_results = observation_data.findall('.//' + APT_NAMESPACE + 'Observation')
    n_obs = len(obs_results)

    # Locate catalogs for target(s)
    sw_cats = [os.path.join(TESTS_DIR, 'test_data', '2MASS_RA273.09deg_Dec65.60deg.list')] * n_obs
    lw_cats = [os.path.join(TESTS_DIR, 'test_data', 'WISE_RA273.09deg_Dec65.60deg.list')] * n_obs

    # Point to appropriate output directory
    out_dir = os.path.join(TESTS_DIR, 'test_data',  instrument, 'APT_{}_out'.format(instrument))
    if not os.path.exists(out_dir):
        os.makedirs(out_dir)


    # Write observationlist.yaml
    observationlist_file = os.path.join(out_dir, instrument + '_observationlist.yaml')
    write_observationlist.write_yaml(xml_file, pointing_file, observationlist_file,
                                     ps_cat_sw=sw_cats, ps_cat_lw=lw_cats)

    # Create a series of data simulator input yaml files
    yam = yaml_generator.SimInput()
    yam.input_xml = xml_file
    yam.pointing_file = pointing_file
    yam.siaf = os.path.expandvars('$MIRAGE_DATA/nircam/reference_files/SIAF/NIRCam_SIAF_2018-01-08.csv')
    yam.output_dir = out_dir
    yam.simdata_output_dir = out_dir
    yam.observation_table = observationlist_file
    yam.use_JWST_pipeline = False
    yam.use_linearized_darks = True
    yam.datatype = 'linear'
    yam.reffile_setup()
    yam.create_inputs()

    # Ensure that some of the expected files have been created
    assert os.path.exists(os.path.join(out_dir, 'Observation_table_for_' +
                                                instrument +
                                                'Test.xml_with_yaml_parameters.csv')), \
        'Observation table not created.'
    assert len(glob.glob(os.path.join(out_dir, 'V' + PROPOSAL_ID + '*.yaml'))) \
        >= n_obs, 'Fewer yaml files created than observations'

    # If a reference observationlist.yaml file exists, ensure that the
    # file that was just created matches it
    reference_yaml = os.path.join(out_dir, 'REFERENCE_' + instrument + '_observationlist.yaml')
    if os.path.exists(reference_yaml):
        assert yaml.load(reference_yaml) == yaml.load(observationlist_file),\
            'The created observationlist.yaml file does not match the reference' +\
            'observationlist.yaml file. Either the APT parser is malfunctioning,' +\
            'or the reference yaml is out of date.'


def test_table_length():
    """Check that the .xml and .pointing files agree
    """
    # Define the paths to the NIRCam test XML and pointing files
    pointing_file = os.path.join(TESTS_DIR, 'test_data', 'NIRCam', 'NIRCam' + 'Test.pointing')
    xml_file = os.path.join(TESTS_DIR, 'test_data',  'NIRCam', 'NIRCam' + 'Test.xml')

    # Initialize an AptInput object
    apt = apt_inputs.AptInput()

    # Read in the XML file
    xmltab = apt.create_xml_table(xml_file)

    # Read in the pointing file
    pointing_tab = apt.get_pointing_info(pointing_file, xmltab['ProposalID'][0])

    assert len(xmltab['ProposalID']) == len(pointing_tab['obs_num']),\
        'Inconsistent table size from XML file ({}) and pointing file ({}). Something was not processed correctly in apt_inputs.'.format(len(xmltab['ProposalID']), len(pointing_tab['obs_num']))


@pytest.mark.xfail
def test_environment_variable():
    '''Ensure the MIRAGE_DATA environment variable has been set
    '''
    MIRAGE_DATA = os.path.expandvars('MIRAGE_DATA')
    assert MIRAGE_DATA is not None, "MIRAGE_DATA environment variable is not " +\
                                    "set. This must be set to the base directory" +\
                                    " containing the darks, cosmic ray, PSF, etc" +\
                                    " input files needed for the simulation. " +\
                                    "These files must be downloaded separately " +\
                                    "from the Mirage package."


@pytest.mark.xfail
def test_RunNIRCamAPTTemplates():
    '''Parse the given APT files and create a set of .yamls for NIRCam
    '''
    RunAllAPTTemplates('NIRCam')


def test_trivial():
    assert 1==1


