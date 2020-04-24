import pandas as pd
from collections import ChainMap
from rstl import STL
import numpy as np
import statsmodels.api as sm
from statsmodels.tsa.stattools import acf
from statsmodels.tsa.stattools import pacf
from entropy import spectral_entropy
from statsmodels.tsa.holtwinters import ExponentialSmoothing
import multiprocessing as mp
from sklearn.linear_model import LinearRegression
from itertools import groupby
from statsmodels.tsa.ar_model import AR
from statsmodels.tsa.stattools import acf
from arch import arch_model
import logging
from supersmoother import SuperSmoother

def poly(x, p):
    x = np.array(x)
    X = np.transpose(np.vstack(list((x**k for k in range(p+1)))))
    return np.linalg.qr(X)[0][:,1:]

def embed(x, p):
    x = np.array(x)
    x = np.transpose(np.vstack(list((np.roll(x, k) for k in range(p)))))
    x = x[(p-1):]

    return x

def acf_features(x):
    ### Unpacking series
    (x, m) = x
    if m is None:
        m = 1
    size_x = len(x)

    acfx = acf(x, nlags = max(m, 10), fft=False)
    if size_x > 10:
        acfdiff1x = acf(np.diff(x, n = 1), nlags =  10, fft=False)
    else:
        acfdiff1x = [np.nan]*2

    if size_x > 11:
        acfdiff2x = acf(np.diff(x, n = 2), nlags =  10, fft=False)
    else:
        acfdiff2x = [np.nan]*2

    # first autocorrelation coefficient
    acf_1 = acfx[1]

    # sum of squares of first 10 autocorrelation coefficients
    sum_of_sq_acf10 = np.sum((acfx[1:11])**2) if size_x > 10 else np.nan

    # first autocorrelation ciefficient of differenced series
    diff1_acf1 = acfdiff1x[1]

    # sum of squared of first 10 autocorrelation coefficients of differenced series
    diff1_acf10 = np.sum((acfdiff1x[1:11])**2) if size_x > 10 else np.nan

    # first autocorrelation coefficient of twice-differenced series
    diff2_acf1 = acfdiff2x[1]

    # Sum of squared of first 10 autocorrelation coefficients of twice-differenced series
    diff2_acf10 = np.sum((acfdiff2x[1:11])**2) if size_x > 11 else np.nan

    output = {
        'x_acf1': acf_1,
        'x_acf10': sum_of_sq_acf10,
        'diff1_acf1': diff1_acf1,
        'diff1_acf10': diff1_acf10,
        'diff2_acf1': diff2_acf1,
        'diff2_acf10': diff2_acf10
    }

    if m > 1:
        output['seas_acf1'] = acfx[m] if len(acfx) > m else np.nan

    return output

def pacf_features(x):
    """
    Partial autocorrelation function features.
    """
    ### Unpacking series
    (x, m) = x
    if m is None:
        m = 1
    nlags_ = max(m, 5)

    if len(x) > 1:
        try:
            pacfx = pacf(x, nlags = nlags_, method='ldb')
        except:
            pacfx = np.nan
    else:
        pacfx = np.nan

    # Sum of first 6 PACs squared
    if len(x) > 5:
        pacf_5 = np.sum(pacfx[1:6]**2)
    else:
        pacf_5 = np.nan

    # Sum of first 5 PACs of difference series squared
    if len(x) > 6:
        try:
            diff1_pacf = pacf(np.diff(x, n = 1), nlags = 5, method='ldb')[1:6]
            diff1_pacf_5 = np.sum(diff1_pacf**2)
        except:
            diff1_pacf_5 = np.nan
    else:
        diff1_pacf_5 = np.nan


    # Sum of first 5 PACs of twice differenced series squared
    if len(x) > 7:
        try:
            diff2_pacf = pacf(np.diff(x, n = 2), nlags = 5, method='ldb')[1:6]
            diff2_pacf_5 = np.sum(diff2_pacf**2)
        except:
            diff2_pacf_5 = np.nan
    else:
        diff2_pacf_5 = np.nan

    output = {
        'x_pacf5': pacf_5,
        'diff1x_pacf5': diff1_pacf_5,
        'diff2x_pacf5': diff2_pacf_5
    }

    if m > 1:
        output['seas_pacf'] = pacfx[m] if len(pacfx) > m else np.nan

    return output

def holt_parameters(x):
    ### Unpacking series
    (x, m) = x
    try :
        fit = ExponentialSmoothing(x, trend = 'add').fit()
        params = {
            'alpha': fit.params['smoothing_level'],
            'beta': fit.params['smoothing_slope']
        }
    except:
        params = {
            'alpha': np.nan,
            'beta': np.nan
        }

    return params


def hw_parameters(x):
    ### Unpacking series
    (x, m) = x
    # Hack: ExponentialSmothing needs a date index
    # this must be fixed
    dates_hack = pd.date_range(end = '2019-01-01', periods = len(x))
    try:
        fit = ExponentialSmoothing(x, trend = 'add', seasonal = 'add', dates = dates_hack).fit()
        params = {
            'hwalpha': fit.params['smoothing_level'],
            'hwbeta': fit.params['smoothing_slope'],
            'hwgamma': fit.params['smoothing_seasonal']
        }
    except:
        params = {
            'hwalpha': np.nan,
            'hwbeta': np.nan,
            'hwgamma': np.nan
        }
    return params

# features

def entropy(x):
    ### Unpacking series
    (x, m) = x
    try:
        # Maybe 100 can change
        entropy = spectral_entropy(x, 1)
    except:
        entropy = np.nan

    return {'entropy': entropy}

def lumpiness(x):
    ### Unpacking series
    (x, width) = x

    if width == 1:
        width = 10

    nr = len(x)
    lo = np.arange(0, nr, width)
    up = lo + width
    nsegs = nr / width
    varx = [np.nanvar(x[lo[idx]:up[idx]], ddof=1) for idx in np.arange(int(nsegs))]
    print(varx)

    if len(x) < 2*width:
        lumpiness = 0
    else:
        lumpiness = np.nanvar(varx, ddof=1)

    return {'lumpiness': lumpiness}

def stability(x):
    ### Unpacking series
    (x, width) = x

    if width == 1:
        width = 10

    nr = len(x)
    lo = np.arange(0, nr, width)
    up = lo + width
    nsegs = nr / width
    #print(np.arange(nsegs))
    meanx = [np.nanmean(x[lo[idx]:up[idx]]) for idx in np.arange(int(nsegs))]

    if len(x) < 2*width:
        stability = 0
    else:
        stability = np.nanvar(meanx, ddof=1)

    return {'stability': stability}

def crossing_points(x):
    (x, m) = x
    midline = np.median(x)
    ab = x <= midline
    lenx = len(x)
    p1 = ab[:(lenx-1)]
    p2 = ab[1:]
    cross = (p1 & (~p2)) | (p2 & (~p1))
    return {'crossing_points': cross.sum()}

def flat_spots(x):
    (x, m) = x
    try:
        cutx = pd.cut(x, bins=10, include_lowest=True, labels=False) + 1
    except:
        return {'flat_spots': np.nan}

    rlex = np.array([sum(1 for i in g) for k,g in groupby(cutx)]).max()

    return {'flat_spots': rlex}

def heterogeneity(x):
    (x, m) = x
    size_x = len(x)
    order_ar = min(size_x-1, 10*np.log10(size_x)).astype(int) # Defaults for
    x_whitened = AR(x).fit(maxlag = order_ar).resid

    # arch and box test
    x_archtest = arch_stat((x_whitened, m))['arch_lm']
    LBstat = (acf(x_whitened**2, nlags=12, fft=False)[1:]**2).sum()

    #Fit garch model
    garch_fit = arch_model(x_whitened, vol='GARCH', rescale=False).fit(disp='off')

    # compare arch test before and after fitting garch
    garch_fit_std = garch_fit.resid
    x_garch_archtest = arch_stat((garch_fit_std, m))['arch_lm']

    # compare Box test of squared residuals before and after fittig.garch
    LBstat2 = (acf(garch_fit_std**2, nlags=12, fft=False)[1:]**2).sum()

    output = {
        'arch_acf': LBstat,
        'garch_acf': LBstat2,
        'arch_2': x_archtest,
        'garch_r2': x_garch_archtest
    }

    return output

def series_length(x):
    (x, m) = x

    return {'series_length': len(x)}
# Time series features based of sliding windows
#def max_level_shift(x):
#    width = 7 # This must be changed


def frequency(x):
    ### Unpacking series
    (x, m) = x
    # Needs frequency of series
    return {'frequency': m}#x.index.freq}

def scalets(x):
    # Scaling time series
    scaledx = (x - x.mean())/x.std()
    #ts = pd.Series(scaledx, index=x.index)
    return scaledx

def stl_features(x):
    """
    Returns a DF where each column is an statistic.
    """
    ### Unpacking series
    (x, m) = x
    # Size of ts
    nperiods = int(m > 1)
    # STL fits
    if m>1:
        stlfit = STL(np.array(x), m, 13)
        trend0 = stlfit.trend
        remainder = stlfit.remainder
        #print(len(remainder))
        seasonal = stlfit.seasonal
    else:
        seasonal = np.array(x)
        t = np.arange(len(x))+1
        trend0 = SuperSmoother().fit(t, seasonal).predict(t)
        remainder = seasonal - trend0

    # De-trended and de-seasonalized data
    detrend = x - trend0
    deseason = x - seasonal
    fits = x - remainder

    # Summay stats
    n = len(x)
    varx = np.nanvar(x, ddof=1)
    vare = np.nanvar(remainder, ddof=1)
    vardetrend = np.nanvar(detrend, ddof=1)
    vardeseason = np.nanvar(deseason, ddof=1)

    #Measure of trend strength
    if varx < np.finfo(float).eps:
        trend = 0
    elif (vardeseason/varx < 1e-10):
        trend = 0
    else:
        trend = max(0, min(1, 1 - vare/vardeseason))

    # Measure of seasonal strength
    if m > 1:
        if varx < np.finfo(float).eps:
            season = 0
        elif np.nanvar(remainder + seasonal, ddof=1) < np.finfo(float).eps:
            season = 0
        else:
            season = max(0, min(1, 1 - vare/np.nanvar(remainder + seasonal, ddof=1)))

        peak = (np.argmax(x)+1) % m
        peak = m if peak == 0 else peak

        trough = (np.argmin(x)+1) % m
        trough = m if trough == 0 else trough



    # Compute measure of spikiness
    d = (remainder - np.nanmean(remainder))**2
    varloo = (vare*(n-1)-d)/(n-2)
    spike = np.nanvar(varloo, ddof=1)

    # Compute measures of linearity and curvature
    time = np.arange(n) + 1
    poly_m = poly(time, 2)
    time_x = sm.add_constant(poly_m)
    coefs = sm.OLS(trend0, time_x).fit().params

    linearity = coefs[1]
    curvature = coefs[2]

    # ACF features
    acfremainder = acf_features((remainder, m))

    # Assemble features
    output = {
        'nperiods': nperiods,
        'seasonal_period': m,
        'trend': trend,
        'spike': spike,
        'linearity': linearity,
        'curvature': curvature,
        'e_acf1': acfremainder['x_acf1'],
        'e_acf10': acfremainder['x_acf10']
    }

    if m>1:
        output['seasonal_strength'] = season
        output['peak'] = peak
        output['trough'] = trough

    return output

def sparsity(x):
    (x, m) = x
    return {'sparsity': np.mean(x == 0)}

#### Heterogeneity coefficients

#ARCH LM statistic
def arch_stat(x, lags=12, demean=True):
    (x, m) = x
    if len(x) <= lags+1:
        return {'arch_lm': np.nan}
    if demean:
        x -= np.mean(x)

    size_x = len(x)
    mat = embed(x**2, lags+1)
    X = mat[:,1:]
    y = np.vstack(mat[:, 0])

    #try:
    r_squared = LinearRegression().fit(X, y).score(X, y)
    #except:
    #    r_squared = np.nan

    return {'arch_lm': r_squared}

# Main functions
def _get_feats(tuple_ts_features):
    (ts_, features) = tuple_ts_features
    c_map = ChainMap(*[dict_feat for dict_feat in [func(ts_) for func in features]])

    return pd.DataFrame(dict(c_map), index = [0])

def tsfeatures(
            tslist,
            frcy,
            features = [
                stl_features,
                frequency,
                entropy,
                acf_features,
                pacf_features,
                holt_parameters,
                hw_parameters,
                #entropy,
                lumpiness,
                stability,
                arch_stat,
                series_length,
                #heterogeneity,
                flat_spots,
                crossing_points,
                sparsity
            ],
            scale = True,
            parallel = False,
            threads = None
    ):
    """
    tslist: list of numpy arrays or pandas Series class
    """
    if not isinstance(tslist, list):
        tslist = [tslist]

    sp = None
    # Scaling
    if scale:
        if sparsity in features:
            features = [feat for feat in features if feat is not sparsity]
            if parallel:
                with mp.Pool(threads) as pool:
                    sp = pool.map(sparsity, [(y, frcy) for y in tslist])
            else:
                sp = [sparsity((ts, frcy)) for ts in tslist]
            sp = pd.DataFrame(sp)
        # Parallel
        if parallel:
            with mp.Pool(threads) as pool:
                tslist = pool.map(scalets, tslist)
        else:
            tslist = [scalets(ts) for ts in tslist]


    # There's methods which needs frequency
    # This is a hack for this
    # each feature function receives a tuple (ts, frcy)
    tslist = [(ts, frcy) for ts in tslist]

    # Init parallel
    if parallel:
        n_series = len(tslist)
        with mp.Pool(threads) as pool:
            ts_features = pool.map(_get_feats, zip(tslist, [features for i in range(n_series)]))
    else:
        ts_features = [_get_feats((ts, features)) for ts in tslist]


    feat_df = pd.concat(ts_features).reset_index(drop=True)
    if sp is not None:
        feat_df = pd.concat([feat_df, sp], axis=1)

    return feat_df
