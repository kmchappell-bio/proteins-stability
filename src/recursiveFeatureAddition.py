
# Author: Henry Heberle
# Modified from the RFE code in this manner:
# Instead of elimination the worst feature, the algorithm eliminate the best feature.
# In the end of the process, instead or returning <ranking>, it will return <reverse(ranking)>
# So that the first feature eliminated will be the most important one in the ranking.
#
# Authors of RFE: Alexandre Gramfort <alexandre.gramfort@inria.fr>
#          Vincent Michel <vincent.michel@inria.fr>
#          Gilles Louppe <g.louppe@gmail.com>
#
# License: BSD 3 clause

"""Recursive Feature Addition (RFA) for feature ranking"""

import numpy as np
from sklearn.utils import check_X_y, safe_sqr
from sklearn.utils.metaestimators import if_delegate_has_method
from sklearn.utils.validation import check_is_fitted
from sklearn.base import BaseEstimator
from sklearn.base import MetaEstimatorMixin
from sklearn.base import clone
from sklearn.base import is_classifier
#from sklearn.externals.joblib import Parallel, delayed
from joblib import Parallel, delayed
from sklearn.model_selection import check_cv
from sklearn.model_selection._validation import _safe_split, _score
#from sklearn.metrics.scorer import check_scoring
from sklearn.metrics import check_scoring
#from sklearn.feature_selection.base import SelectorMixin
from sklearn.feature_selection import SelectorMixin


def _rfa_single_fit(rfa, estimator, X, y, train, test, scorer):
    """
    Return the score for a fit across one fold.
    """
    X_train, y_train = _safe_split(estimator, X, y, train)
    X_test, y_test = _safe_split(estimator, X, y, test, train)
    return rfa._fit(
        X_train, y_train, lambda estimator, features:
        _score(estimator, X_test[:, features], y_test, scorer)).scores_


class RFA(BaseEstimator, MetaEstimatorMixin, SelectorMixin):
    """Feature ranking with recursive feature addition.

    Given an external estimator that assigns weights to features (e.g., the
    coefficients of a linear model), the goal of recursive feature addition
    (RFA) is to select features by recursively considering smaller and smaller
    sets of features. First, the estimator is trained on the initial set of
    features and the importance of each feature is obtained either through a
    ``coef_`` attribute or through a ``feature_importances_`` attribute.
    Then, the most important features are added to a new set of features.
    That procedure is recursively repeated on the remaining features until the
    desired number of features to select is eventually reached.

    Read more in the :ref:`User Guide <rfa>`.

    Parameters
    ----------
    estimator : object
        A supervised learning estimator with a ``fit`` method that provides
        information about feature importance either through a ``coef_``
        attribute or through a ``feature_importances_`` attribute.

    n_features_to_select : int or None (default=None)
        The number of features to select. If `None`, half of the features
        are selected.

    step : int or float, optional (default=1)
        If greater than or equal to 1, then `step` corresponds to the (integer)
        number of features to remove at each iteration.
        If within (0.0, 1.0), then `step` corresponds to the percentage
        (rounded down) of features to remove at each iteration.

    verbose : int, default=0
        Controls verbosity of output.

    Attributes
    ----------
    n_features_ : int
        The number of selected features.

    support_ : array of shape [n_features]
        The mask of selected features.

    ranking_ : array of shape [n_features]
        The feature ranking, such that ``ranking_[i]`` corresponds to the
        ranking position of the i-th feature. Selected (i.e., estimated
        best) features are assigned rank 1.

    estimator_ : object
        The external estimator fit on the reduced dataset.

    Examples
    --------
    The following example shows how to retrieve the 5 right informative
    features in the Friedman #1 dataset.

    >>> from sklearn.datasets import make_friedman1
    >>> from sklearn.feature_selection import RFA
    >>> from sklearn.svm import SVR
    >>> X, y = make_friedman1(n_samples=50, n_features=10, random_state=0)
    >>> estimator = SVR(kernel="linear")
    >>> selector = RFA(estimator, 5, step=1)
    >>> selector = selector.fit(X, y)
    >>> selector.support_ # doctest: +NORMALIZE_WHITESPACE
    # TODO run the RFA and print the result
    array([ True  True  True  True False False False  True False False], dtype=bool)
    >>> selector.ranking_
    array([1 1 1 1 2 5 6 1 4 3])

    References
    ----------

    ..  # todo Is there any reference? Otherwise put your own Thesis

    """
    def __init__(self, estimator, n_features_to_select=None, step=1,
                 verbose=0):
        self.estimator = estimator
        self.n_features_to_select = n_features_to_select
        self.step = step
        self.verbose = verbose

    @property
    def _estimator_type(self):
        return self.estimator._estimator_type

    def fit(self, X, y):
        """Fit the RFA model and then the underlying estimator on the selected
           features.

        Parameters
        ----------
        X : {array-like, sparse matrix}, shape = [n_samples, n_features]
            The training input samples.

        y : array-like, shape = [n_samples]
            The target values.
        """
        return self._fit(X, y)

    def _fit(self, X, y, step_score=None):
        # Parameter step_score controls the calculation of self.scores_
        # step_score is not exposed to users
        # and is used when implementing RFACV
        # self.scores_ will not be calculated when calling _fit through fit

        X, y = check_X_y(X, y, "csc")
        # Initialization
        n_features = X.shape[1]
        if self.n_features_to_select is None:
            n_features_to_select = n_features // 2
        else:
            n_features_to_select = self.n_features_to_select

        if 0.0 < self.step < 1.0:
            step = int(max(1, self.step * n_features))
        else:
            step = int(self.step)
        if step <= 0:
            raise ValueError("Step must be >0")

        support_added_ = np.zeros(n_features, dtype=np.bool)
        support_ = np.ones(n_features, dtype=np.bool)
        ranking_ = np.ones(n_features, dtype=np.int)
        ranking_added_ = np.ones(n_features, dtype=np.int)

        if step_score:
            self.scores_ = []

        # Adding
        while np.sum(support_) > n_features_to_select:
            # Remaining features
            features = np.arange(n_features)[support_]

            # Added features
            features_added = np.arange(n_features)[support_added_]
            
            # Compute step score on the previous added features
            if step_score and np.sum(support_added_) > 0:
                estimator_added = clone(self.estimator)
                estimator_added.fit(X[:, features_added], y)
                self.scores_.append(step_score(estimator_added, features_added))

            # Rank the remaining features
            estimator = clone(self.estimator)
            if self.verbose > 0:
                print("Fitting estimator with %d features." % np.sum(support_))

            
            estimator.fit(X[:, features], y)           

            # Get coefs
            if hasattr(estimator, 'coef_'):
                coefs = estimator.coef_  
            else:
                coefs = getattr(estimator, 'feature_importances_', None)
            if coefs is None:
                raise RuntimeError('The classifier does not expose '
                                   '"coef_" or "feature_importances_" '
                                   'attributes')

            # Get ranks
            # ! For RFA, the rank is inverted: (np.argsort(list) replaced by (np.argsort(-list)
            if coefs.ndim > 1:
                try:                
                    ranks = np.argsort(-safe_sqr(coefs).sum(axis=0))
                except ValueError:
                    coefs = np.nan_to_num(coefs)
                    ranks = np.argsort(-safe_sqr(coefs).sum(axis=0))
            else:
                try:                
                    ranks = np.argsort(-safe_sqr(coefs))
                except ValueError:
                    coefs = np.nan_to_num(coefs)
                    ranks = np.argsort(-safe_sqr(coefs))

            # for sparse case ranks is matrix
            ranks = np.ravel(ranks)

            # Add the best features
            threshold = min(step, np.sum(support_) - n_features_to_select)
            
            # remaining features to test
            support_[features[ranks][:threshold]] = False
            ranking_[np.logical_not(support_)] += 1

            # added/ranked features            
            support_added_[features[ranks][:threshold]] = True
            ranking_added_[np.logical_not(support_added_)] += 1
            

        # Set final attributes
        features_added = np.arange(n_features)[support_added_]
        self.estimator_ = clone(self.estimator)
        self.estimator_.fit(X[:, features_added], y)

        # Compute step score when only n_features_to_select features left
        if step_score:            
            self.scores_.append(step_score(self.estimator_, features_added))

        self.n_features_ = support_added_.sum()
        self.support_ = support_added_
        self.ranking_ = ranking_added_

        return self

    @if_delegate_has_method(delegate='estimator')
    def predict(self, X):
        """Reduce X to the selected features and then predict using the
           underlying estimator.

        Parameters
        ----------
        X : array of shape [n_samples, n_features]
            The input samples.

        Returns
        -------
        y : array of shape [n_samples]
            The predicted target values.
        """
        check_is_fitted(self, 'estimator_')
        return self.estimator_.predict(self.transform(X))

    @if_delegate_has_method(delegate='estimator')
    def score(self, X, y):
        """Reduce X to the selected features and then return the score of the
           underlying estimator.

        Parameters
        ----------
        X : array of shape [n_samples, n_features]
            The input samples.

        y : array of shape [n_samples]
            The target values.
        """
        check_is_fitted(self, 'estimator_')
        return self.estimator_.score(self.transform(X), y)

    def _get_support_mask(self):
        check_is_fitted(self, 'support_')
        return self.support_

    @if_delegate_has_method(delegate='estimator')
    def decision_function(self, X):
        check_is_fitted(self, 'estimator_')
        return self.estimator_.decision_function(self.transform(X))

    @if_delegate_has_method(delegate='estimator')
    def predict_proba(self, X):
        check_is_fitted(self, 'estimator_')
        return self.estimator_.predict_proba(self.transform(X))

    @if_delegate_has_method(delegate='estimator')
    def predict_log_proba(self, X):
        check_is_fitted(self, 'estimator_')
        return self.estimator_.predict_log_proba(self.transform(X))


class RFACV(RFA, MetaEstimatorMixin):
    """Feature ranking with recursive feature elimination and cross-validated
    selection of the best number of features.

    Read more in the :ref:`User Guide <rfa>`.

    Parameters
    ----------
    estimator : object
        A supervised learning estimator with a ``fit`` method that provides
        information about feature importance either through a ``coef_``
        attribute or through a ``feature_importances_`` attribute.

    step : int or float, optional (default=1)
        If greater than or equal to 1, then `step` corresponds to the (integer)
        number of features to remove at each iteration.
        If within (0.0, 1.0), then `step` corresponds to the percentage
        (rounded down) of features to remove at each iteration.

    cv : int, cross-validation generator or an iterable, optional
        Determines the cross-validation splitting strategy.
        Possible inputs for cv are:

        - None, to use the default 3-fold cross-validation,
        - integer, to specify the number of folds.
        - An object to be used as a cross-validation generator.
        - An iterable yielding train/test splits.

        For integer/None inputs, if ``y`` is binary or multiclass,
        :class:`sklearn.model_selection.StratifiedKFold` is used. If the
        estimator is a classifier or if ``y`` is neither binary nor multiclass,
        :class:`sklearn.model_selection.KFold` is used.

        Refer :ref:`User Guide <cross_validation>` for the various
        cross-validation strategies that can be used here.

    scoring : string, callable or None, optional, default: None
        A string (see model evaluation documentation) or
        a scorer callable object / function with signature
        ``scorer(estimator, X, y)``.

    verbose : int, default=0
        Controls verbosity of output.

    n_jobs : int, default 1
        Number of cores to run in parallel while fitting across folds.
        Defaults to 1 core. If `n_jobs=-1`, then number of jobs is set
        to number of cores.

    Attributes
    ----------
    n_features_ : int
        The number of selected features with cross-validation.

    support_ : array of shape [n_features]
        The mask of selected features.

    ranking_ : array of shape [n_features]
        The feature ranking, such that `ranking_[i]`
        corresponds to the ranking
        position of the i-th feature.
        Selected (i.e., estimated best)
        features are assigned rank 1.

    grid_scores_ : array of shape [n_subsets_of_features]
        The cross-validation scores such that
        ``grid_scores_[i]`` corresponds to
        the CV score of the i-th subset of features.

    estimator_ : object
        The external estimator fit on the reduced dataset.

    Notes
    -----
    The size of ``grid_scores_`` is equal to ceil((n_features - 1) / step) + 1,
    where step is the number of features removed at each iteration.

    Examples
    --------
    The following example shows how to retrieve the a-priori not known 5
    informative features in the Friedman #1 dataset.

    >>> from sklearn.datasets import make_friedman1
    >>> from sklearn.feature_selection import RFACV
    >>> from sklearn.svm import SVR
    >>> X, y = make_friedman1(n_samples=50, n_features=10, random_state=0)
    >>> estimator = SVR(kernel="linear")
    >>> selector = RFACV(estimator, step=1, cv=5)
    >>> selector = selector.fit(X, y)
    >>> selector.support_ # doctest: +NORMALIZE_WHITESPACE
    array([ True,  True,  True,  True,  True,
            False, False, False, False, False], dtype=bool)
    >>> selector.ranking_
    array([1, 1, 1, 1, 1, 6, 4, 3, 2, 5])

    References
    ----------

    .. [1] Guyon, I., Weston, J., Barnhill, S., & Vapnik, V., "Gene selection
           for cancer classification using support vector machines",
           Mach. Learn., 46(1-3), 389--422, 2002.
    """
    def __init__(self, estimator, step=1, cv=None, scoring=None, verbose=0,
                 n_jobs=1):
        self.estimator = estimator
        self.step = step
        self.cv = cv
        self.scoring = scoring
        self.verbose = verbose
        self.n_jobs = n_jobs

    def fit(self, X, y):
        """Fit the RFA model and automatically tune the number of selected
           features.

        Parameters
        ----------
        X : {array-like, sparse matrix}, shape = [n_samples, n_features]
            Training vector, where `n_samples` is the number of samples and
            `n_features` is the total number of features.

        y : array-like, shape = [n_samples]
            Target values (integers for classification, real numbers for
            regression).
        """
        X, y = check_X_y(X, y, "csr")

        # Initialization
        cv = check_cv(self.cv, y, is_classifier(self.estimator))
        scorer = check_scoring(self.estimator, scoring=self.scoring)
        n_features = X.shape[1]
        n_features_to_select = 1

        if 0.0 < self.step < 1.0:
            step = int(max(1, self.step * n_features))
        else:
            step = int(self.step)
        if step <= 0:
            raise ValueError("Step must be >0")

        rfa = RFA(estimator=self.estimator,
                  n_features_to_select=n_features_to_select,
                  step=self.step, verbose=self.verbose)

        # Determine the number of subsets of features by fitting across
        # the train folds and choosing the "features_to_select" parameter
        # that gives the least averaged error across all folds.

        # Note that joblib raises a non-picklable error for bound methods
        # even if n_jobs is set to 1 with the default multiprocessing
        # backend.
        # This branching is done so that to
        # make sure that user code that sets n_jobs to 1
        # and provides bound methods as scorers is not broken with the
        # addition of n_jobs parameter in version 0.18.

        print("=============================")
        if self.n_jobs == 1:
            parallel, func = list, _rfa_single_fit
        else:
            parallel, func, = Parallel(n_jobs=self.n_jobs), delayed(_rfa_single_fit)

        scores = parallel(
            func(rfa, self.estimator, X, y, train, test, scorer)
            for train, test in cv.split(X, y))

        scores = np.sum(scores, axis=0)

        # print(scores)
        # print(np.argmax(scores))

        n_features_to_select = max(
            n_features - (np.argmax(scores) * step),
            n_features_to_select)

        # Re-execute an elimination with best_k over the whole set
        rfa = RFA(estimator=self.estimator,
                  n_features_to_select=n_features_to_select, step=self.step)

        rfa.fit(X, y)

        # Set final attributes
        self.support_ = rfa.support_
        self.n_features_ = rfa.n_features_
        self.ranking_ = rfa.ranking_
        self.estimator_ = clone(self.estimator)
        self.estimator_.fit(self.transform(X), y)

        # Fixing a normalization error, n is equal to get_n_splits(X, y) - 1
        # here, the scores are normalized by get_n_splits(X, y)
        self.grid_scores_ = scores[::-1] / cv.get_n_splits(X, y)
        return self

if __name__ == "__main__":
    

    from sklearn.datasets import make_friedman1
    from sklearn.svm import SVR
    from sklearn.metrics import make_scorer, matthews_corrcoef, cohen_kappa_score
    matthews_scorer = make_scorer(matthews_corrcoef)
    kappa_scorer = make_scorer(cohen_kappa_score)

    print("\nTesting RFA\n")
    X, y = make_friedman1(n_samples=50, n_features=10, random_state=0)
    estimator = SVR(kernel="linear")
    selector = RFA(estimator, 5, step=1)
    selector = selector.fit(X, y)
    print(selector.support_) # doctest: +NORMALIZE_WHITESPACE
    # TODO run the RFA and print the result
    #array([ True,  True,  True,  True,  True,
            #False, False, False, False, False], dtype=bool)
    print(selector.ranking_)

    print("\nTesting RFACV\n")
    selector = RFACV(estimator, step=1, cv=5)
    selector = selector.fit(X, y)
    print(selector.support_) # doctest: +NORMALIZE_WHITESPACE
    #array([ True,  True,  True,  True,  True,
            #False, False, False, False, False], dtype=bool)
    print(selector.ranking_)
    #array([1, 1, 1, 1, 1, 6, 4, 3, 2, 5])