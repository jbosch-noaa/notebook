"""
Constants and definitions.
Now we need to specify all the names we know for water level, names that
will get used in the CSW search, and also to find data in the datasets that
are returned.  This is ugly and fragile.  There hopefully will be a better
way in the future...
Standard Library.
"""

from lxml import etree
from io import BytesIO
from warnings import warn
try:
    from urllib.request import urlopen
except ImportError:
    from urllib import urlopen

# Scientific stack.
import numpy as np
from pandas import DataFrame, concat, read_csv

# Custom IOOS/ASA modules (available at PyPI).
from owslib import fes
from owslib.ows import ExceptionReport


name_list = ['water_surface_height_above_reference_datum',
             'sea_surface_height_above_geoid',
             'sea_surface_elevation',
             'sea_surface_height_above_reference_ellipsoid',
             'sea_surface_height_above_sea_level',
             'sea_surface_height',
             'water level']

sos_name = 'water_surface_height_above_reference_datum'


def get_Coops_longName(sta):
    """Get longName for specific station from COOPS SOS using DescribeSensor
    request."""
    url = ('http://opendap.co-ops.nos.noaa.gov/ioos-dif-sos/SOS?service=SOS&'
           'request=DescribeSensor&version=1.0.0&'
           'outputFormat=text/xml;subtype="sensorML/1.0.1"&'
           'procedure=urn:ioos:station:NOAA.NOS.CO-OPS:%s') % sta
    tree = etree.parse(urlopen(url))
    root = tree.getroot()
    path = "//sml:identifier[@name='longName']/sml:Term/sml:value/text()"
    namespaces = dict(sml="http://www.opengis.net/sensorML/1.0.1")
    longName = root.xpath(path, namespaces=namespaces)
    if len(longName) == 0:
        longName = sta
    return longName[0]


def coops2df(collector, coops_id, sos_name):
    """Request CSV response from SOS and convert to Pandas DataFrames."""
    collector.features = [coops_id]
    collector.variables = [sos_name]
    long_name = get_Coops_longName(coops_id)

    try:
        response = collector.raw(responseFormat="text/csv")
        data_df = read_csv(BytesIO(response.encode('utf-8')),
                           parse_dates=True,
                           index_col='date_time')
        col = 'water_surface_height_above_reference_datum (m)'
        if False:
            data_df['Observed Data'] = (data_df[col] -
                                        data_df['vertical_position (m)'])
        data_df['Observed Data'] = data_df[col]
    except ExceptionReport as e:
        warn("Station %s is not NAVD datum. %s" % (long_name, e))
        data_df = DataFrame()  # Assing an empty DataFrame for now.

    data_df.name = long_name
    return data_df


def mod_df(arr, timevar, istart, istop, mod_name, ts):
    """Return time series (DataFrame) from model interpolated onto uniform
    time base."""
    t = timevar.points[istart:istop]
    jd = timevar.units.num2date(t)

    # Eliminate any data that is closer together than 10 seconds this was
    # required to handle issues with CO-OPS aggregations, I think because they
    # use floating point time in hours, which is not very accurate, so the
    # FMRC aggregation is aggregating points that actually occur at the same
    # time.
    dt = np.diff(jd)
    s = np.array([ele.seconds for ele in dt])
    ind = np.where(s > 10)[0]
    arr = arr[ind+1]
    jd = jd[ind+1]

    b = DataFrame(arr, index=jd, columns=[mod_name])
    # Eliminate any data with NaN.
    b = b[np.isfinite(b[mod_name])]
    # Interpolate onto uniform time base, fill gaps up to:
    # (10 values @ 6 min = 1 hour).
    c = concat([b, ts], axis=1).interpolate(limit=10)
    return c


def dateRange(start_date='1900-01-01', stop_date='2100-01-01',
              constraint='overlaps'):
    """Hopefully something like this will be implemented in fes soon."""
    if constraint == 'overlaps':
        begin = 'apiso:TempExtent_begin'
        end = 'apiso:TempExtent_end'
        start = fes.PropertyIsLessThanOrEqualTo(propertyname=begin,
                                                literal=stop_date)
        stop = fes.PropertyIsGreaterThanOrEqualTo(propertyname=end,
                                                  literal=start_date)
    elif constraint == 'within':
        start = fes.PropertyIsGreaterThanOrEqualTo(propertyname=begin,
                                                   literal=start_date)
        stop = fes.PropertyIsLessThanOrEqualTo(propertyname=end,
                                               literal=stop_date)
    return start, stop


def service_urls(records, service='odp:url'):
    """Extract service_urls of a specific type (DAP, SOS) from records."""
    service_string = 'urn:x-esri:specification:ServiceType:' + service
    urls = []
    for key, rec in records.iteritems():
        # Create a generator object, and iterate through it until the match is
        # found if not found, gets the default value (here "none").
        url = next((d['url'] for d in rec.references if
                    d['scheme'] == service_string), None)
        if url is not None:
            urls.append(url)
    return urls


def nearxy(x, y, xi, yi):
    """Find the indices x[i] of arrays (x,y) closest to the points (xi,yi)."""
    ind = np.ones(len(xi), dtype=int)
    dd = np.ones(len(xi), dtype='float')
    for i in np.arange(len(xi)):
        dist = np.sqrt((x-xi[i])**2 + (y-yi[i])**2)
        ind[i] = dist.argmin()
        dd[i] = dist[ind[i]]
    return ind, dd


def find_ij(x, y, d, xi, yi):
    """Find non-NaN cell d[j, i] that are closest to points (xi, yi)."""
    index = np.where(~np.isnan(d.flatten()))[0]
    ind, dd = nearxy(x.flatten()[index],
                     y.flatten()[index], xi, yi)
    j, i = ind2ij(x, index[ind])
    return i, j, dd


def find_timevar(cube):
    """Return the time variable from Iris.  This is a workaround for
    Iris having problems with FMRC aggregations, which produce two time
    coordinates."""
    try:
        cube.coord(axis='T').rename('time')
    except:
        pass
    timevar = cube.coord('time')
    return timevar


def ind2ij(a, index):
    """Returns a[j,i] for a.ravel()[index]."""
    n, m = a.shape
    j = np.ceil(index // m)
    i = np.remainder(index, m)
    return i, j
