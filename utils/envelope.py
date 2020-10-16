import numpy as np
import multiprocessing as mp
from multiprocessing import Semaphore
from ..filter import next_fast_len
from ..source_estimate import _BaseSourceEstimate
from ..utils import verbose, _check_combine, _check_option
from multiprocessing import Process, Manager, Value, Pool
from functools import wraps
import time

def convert(seconds): 
    return time.strftime("%H:%M:%S", time.gmtime(n))


def timefn(fn):
    @wraps(fn)
    def measure_time(*args, **kwargs):
        t1 = time.time()
        result = fn(*args, **kwargs)
        t2 = time.time()
        print (f'@timefn: {fn.__name__} took {convert(t2-t1)} (hh:mm:ss.ms)')
        return result
    return measure_time


def compute_correlation(epoch_data, corrs, seed):

        combine='mean'
        orthogonalize="pairwise"
        verbose=None
        epoch_data = epoch_data.data
        n_nodes, n_times = epoch_data.shape
        data_mag = np.abs(epoch_data)

        # Logarithm of the squared amplitude envelope ( Power Envelope ) From Hipps paper
        data_mag = np.log(np.square(data_mag))

        data_conj_scaled = epoch_data.conj()
        data_conj_scaled /= data_mag
        # subtract means
        data_mag_nomean = data_mag - np.mean(data_mag, axis=-1, keepdims=True)
        # compute variances using linalg.norm (square, sum, sqrt) since mean=0
        data_mag_std = np.linalg.norm(data_mag_nomean, axis=-1)
        data_mag_std[data_mag_std == 0] = 1

        corr = np.zeros((n_nodes, 1))
        label_data = epoch_data[seed].copy()

        if orthogonalize is False:  # the new code
            label_data_orth = data_mag
            label_data_orth_std = data_mag_std
        else:
            label_data_orth = (label_data * data_conj_scaled).imag
            label_data_orth -= np.mean(label_data_orth, axis=-1,
                                            keepdims=True)            

            label_data_orth_std = np.linalg.norm(label_data_orth, axis=-1)
            label_data_orth_std[label_data_orth_std == 0] = 1

        # correlation is dot product divided by variances
        corr = np.dot(label_data_orth, data_mag_nomean[seed])
        corr /= data_mag_std[seed]
        corr /= label_data_orth_std

        if orthogonalize is not False:
            # Make it symmetric (it isn't at this point)
            corr = np.abs(corr)
            corr = (corr.T + corr) / 2.
            
        corrs.append(corr)
        del corr


def compute_correlation_serial(data, seed=None):
    """Compute the envelope correlation.

    Parameters
    ----------
    data : array-like, shape=(n_epochs, n_signals, n_times) | generator
        The data from which to compute connectivity.
        The array-like object can also be a list/generator of array,
        each with shape (n_signals, n_times), or a :class:`~mne.SourceEstimate`
        object (and ``stc.data`` will be used). If it's float data,
        the Hilbert transform will be applied; if it's complex data,
        it's assumed the Hilbert has already been applied.
    combine : 'mean' | callable | None
        How to combine correlation estimates across epochs.
        Default is 'mean'. Can be None to return without combining.
        If callable, it must accept one positional input.
        For example::

            combine = lambda data: np.median(data, axis=0)

    orthogonalize : 'pairwise' | False
        Whether to orthogonalize with the pairwise method or not.
        Defaults to 'pairwise'. Note that when False,
        the correlation matrix will not be returned with
        absolute values.

        .. versionadded:: 0.19
    %(verbose)s

    Returns
    -------
    corr : ndarray, shape ([n_epochs, ]n_nodes, n_nodes)
        The pairwise orthogonal envelope correlations.
        This matrix is symmetric. If combine is None, the array
        with have three dimensions, the first of which is ``n_epochs``.

    Notes
    -----
    This function computes the power envelope correlation between
    orthogonalized signals [1]_ [2]_.

    References
    ----------
    .. [1] Hipp JF, Hawellek DJ, Corbetta M, Siegel M, Engel AK (2012)
           Large-scale cortical correlation structure of spontaneous
           oscillatory activity. Nature Neuroscience 15:884–890
    .. [2] Khan S et al. (2018). Maturation trajectories of cortical
           resting-state networks depend on the mediating frequency band.
           Neuroimage 174:57–68
    """

    combine='mean'
    orthogonalize="pairwise"
    verbose=None

    _check_option('orthogonalize', orthogonalize, (False, 'pairwise'))
    from scipy.signal import hilbert
    n_nodes = None
    if combine is not None:
        fun = _check_combine(combine, valid=('mean',))
    else:  # None
        fun = np.array

    corrs = list()
    # Note: This is embarassingly parallel, but the overhead of sending
    # the data to different workers is roughly the same as the gain of
    # using multiple CPUs. And we require too much GIL for prefer='threading'
    # to help.
    #print(data)
    for ei, epoch_data in enumerate(data):
        #print(f'Processing epoch {ei}...')
        # if isinstance(epoch_data, _BaseSourceEstimate):
        #     epoch_data = epoch_data.data
        # if epoch_data.ndim != 2:
        #     raise ValueError('Each entry in data must be 2D, got shape %s'
        #                      % (epoch_data.shape,))
        # n_nodes, n_times = epoch_data.shape
        # if ei > 0 and n_nodes != corrs[0].shape[0]:
        #     raise ValueError('n_nodes mismatch between data[0] and data[%d], '
        #                      'got %s and %s'
        #                      % (ei, n_nodes, corrs[0].shape[0]))
        # # Get the complex envelope (allowing complex inputs allows people
        # # to do raw.apply_hilbert if they want)
        # if epoch_data.dtype in (np.float32, np.float64):
        #     n_fft = next_fast_len(n_times)
        #     epoch_data = hilbert(epoch_data, N=n_fft, axis=-1)[..., :n_times]

        # if epoch_data.dtype not in (np.complex64, np.complex128):
        #     raise ValueError('data.dtype must be float or complex, got %s'
        #                      % (epoch_data.dtype,))
        epoch_data = epoch_data.data
        n_nodes, n_times = epoch_data.shape
        data_mag = np.abs(epoch_data)

        # Logarithm of the squared amplitude envelope ( Power Envelope ) From Hipps paper
        data_mag = np.log(np.square(data_mag))

        data_conj_scaled = epoch_data.conj()
        data_conj_scaled /= data_mag
        # subtract means
        data_mag_nomean = data_mag - np.mean(data_mag, axis=-1, keepdims=True)
        # compute variances using linalg.norm (square, sum, sqrt) since mean=0
        data_mag_std = np.linalg.norm(data_mag_nomean, axis=-1)
        data_mag_std[data_mag_std == 0] = 1
        corr = np.empty((n_nodes, 1))
        

        label_data = epoch_data[seed]
       
       # print('Epoch data removed...') 
        if orthogonalize is False:  # the new code
            label_data_orth = data_mag
            label_data_orth_std = data_mag_std
        else:
            label_data_orth = (label_data * data_conj_scaled).imag
            label_data_orth -= np.mean(label_data_orth, axis=-1,
                                               keepdims=True)            

            label_data_orth_std = np.linalg.norm(label_data_orth, axis=-1)
            label_data_orth_std[label_data_orth_std == 0] = 1

        # correlation is dot product divided by variances
        corr = np.dot(label_data_orth, data_mag_nomean[seed])
        corr /= data_mag_std[seed]
        corr /= label_data_orth_std

        if orthogonalize is not False:
            # Make it symmetric (it isn't at this point)
            corr = np.abs(corr)
            corr = (corr.T + corr) / 2.

        corrs.append(corr)
        del corr

    corr = fun(corrs)
    return corr


@timefn
def envelope_correlation(data, combine='mean', orthogonalize="pairwise",
                         verbose=None, seed=None, n_jobs=18):


    _check_option('orthogonalize', orthogonalize, (False, 'pairwise'))
    from scipy.signal import hilbert
    n_nodes = None
    if combine is not None:
        fun = _check_combine(combine, valid=('mean',))
    else:  # None
        fun = np.array

    pool = mp.Pool(processes=n_jobs)
    manager = mp.Manager()
    corrs = manager.list()
    for ei, epoch_data in enumerate(data):
        pool.apply_async(compute_correlation, args=[epoch_data, corrs, seed])
    pool.close()
    pool.join()

    corrs = list(corrs)
    corr = fun(corrs)
    return corr
