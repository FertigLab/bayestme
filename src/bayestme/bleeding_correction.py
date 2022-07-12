'''
Same as bleed_correction8.py except now we use separate basis functions for in-tissue and out-out-tissue.
The hope is that this enables us to account for tissue friction which seems to be an issue.
'''
import torch
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import os.path
import math
import logging

from typing import Optional

from scipy.stats import multivariate_normal, multivariate_t
from torch.nn import Softmax, Softplus
from bayestme.utils import stable_softmax
from bayestme import data, utils, plotting
from autograd_minimize import minimize
from torch.nn import Softplus
from torch.distributions.multinomial import Multinomial
from scipy.stats import multinomial

logger = logging.getLogger(__name__)


def generate_data(
        n_rows=30,
        n_cols=30,
        n_genes=20,
        spot_bleed_prob=0.5,
        length_scale=0.2,
        gene_bandwidth=1,
        bleeding='anisotropic'):
    """
    Generate simulated read data with modeled bleeding.

    :param n_rows: Number of spot rows
    :param n_cols: Number of spot columns
    :param n_genes: Number of genes in output reads dataset
    :param spot_bleed_prob: Tuning param
    :param length_scale: Tuning param
    :param gene_bandwidth: Tuning param
    :param bleeding: Type of bleeding
    :return: (locations, tissue_mask, true_rates, true_counts, bleed_counts)
    """
    xygrid = np.meshgrid(np.arange(n_rows), np.arange(n_cols))
    locations = np.array([xygrid[0].reshape(-1), xygrid[1].reshape(-1)]).T

    # In-tissue region is the central half
    tissue_mask = ((locations[:, 0] > n_rows / 4) & (locations[:, 0] < n_rows / 4 * 3) &
                   (locations[:, 1] > n_cols / 4) & (locations[:, 1] < n_cols / 4 * 3))

    # Sample the true gene reads
    true_rates = np.zeros((n_rows * n_cols, n_genes))
    true_rates[tissue_mask] = np.random.gamma(20, 10, size=(1, n_genes))

    # Make the genes vary in space, except gene 1 which is a control example
    Cov = length_scale * np.exp(
        -np.array([((l[None] - locations[tissue_mask]) ** 2).sum(axis=-1) for l in locations[tissue_mask]]) / (
                2 * gene_bandwidth ** 2)) + np.diag(np.ones(tissue_mask.sum()) * 1e-4)

    for g in range(1, n_genes):
        true_rates[tissue_mask, g] *= np.exp(np.random.multivariate_normal(np.zeros(tissue_mask.sum()), Cov))

        # Insert some regions of sparsity
        start = np.array([n_rows / 2, n_cols / 2])

        # Add a random offset
        start = np.round(start + (np.random.random(size=2) * 2 - 1) * np.array([n_rows / 4, n_cols / 4])).astype(int)

        # Draw a box of sparsity
        width = n_rows // 6
        height = n_cols // 6
        sparsity_mask = ((locations[:, 0] >= start[0]) & (locations[:, 0] < start[0] + width) &
                         (locations[:, 1] >= start[1]) & (locations[:, 1] < start[1] + height))

        true_rates[sparsity_mask, g] = 0

    true_counts = np.random.poisson(true_rates * spot_bleed_prob)

    # Add some anisotropic bleeding
    bleed_counts = np.zeros_like(true_counts)
    if bleeding == 'gaussian':
        x, y = np.meshgrid(np.arange(n_rows), np.arange(n_cols))
        pos = np.dstack((x, y))
        for i in range(tissue_mask.sum()):
            x_cor, y_cor = locations[tissue_mask][i]
            rv_gaus = multivariate_normal([x_cor, y_cor], [[5, 1], [1, 5]])
            for g in range(n_genes):
                bleed_counts[:, g] += np.random.multinomial(true_counts[tissue_mask][i, g], rv_gaus.pdf(pos).flatten())
    elif bleeding == 't':
        x, y = np.meshgrid(np.arange(n_rows), np.arange(n_cols))
        pos = np.dstack((x, y))
        for i in range(tissue_mask.sum()):
            x_cor, y_cor = locations[tissue_mask][i]
            rv_t = multivariate_t([x_cor, y_cor], [[20, 3], [3, 30]], df=10)
            for g in range(n_genes):
                bleed_counts[:, g] += np.random.multinomial(true_counts[tissue_mask][i, g], rv_t.pdf(pos).flatten())
    elif bleeding == 'anisotropic':
        Distances = np.zeros((n_rows * n_cols, n_rows * n_cols, 4))
        true_w = np.array([0.2, 0.03, 1.5, 0.05])
        true_BleedProbs = np.zeros((n_rows * n_cols, n_rows * n_cols))
        for i in range(n_rows * n_cols):
            if i % 100 == 0:
                print(i)
            Distances[:, i, 0] = (locations[i, 0] - locations[:, 0]).clip(0, None) ** 2
            Distances[:, i, 1] = (locations[:, 0] - locations[i, 0]).clip(0, None) ** 2
            Distances[:, i, 2] = (locations[i, 1] - locations[:, 1]).clip(0, None) ** 2
            Distances[:, i, 3] = (locations[:, 1] - locations[i, 1]).clip(0, None) ** 2
            h = np.exp(-Distances[:, i].dot(true_w))
            true_BleedProbs[:, i] = h / h.sum()
            for g in range(n_genes):
                bleed_counts[:, g] += np.random.multinomial(true_counts[i, g], true_BleedProbs[:, i])

    # Add the counts due to non-bleeding
    local_counts = np.random.poisson(true_rates * (1 - spot_bleed_prob))
    true_counts += local_counts
    bleed_counts += local_counts

    return locations, tissue_mask, true_rates, true_counts, bleed_counts


def imshow_matrix(reads, locations, fill=False):
    to_plot = np.full(locations.max(axis=0).astype(int) + 1, np.nan)
    to_plot[locations[:, 0], locations[:, 1]] = reads
    if fill:
        missing = np.where(np.isnan(to_plot))
        to_plot[missing[0], missing[1]] = to_plot[np.minimum(missing[0] + 1, to_plot.shape[0] - 1), missing[1]]
        missing = np.where(np.isnan(to_plot))
        to_plot[missing[0], missing[1]] = to_plot[missing[0] - 1, missing[1]]
    return to_plot


def tissue_mask_to_grid(tissue_mask, locations):
    grid = np.zeros(locations.max(axis=0) + 1)
    grid[locations[:, 0], locations[:, 1]] = tissue_mask
    return grid


def calculate_pairwise_coordinate_differences(locations):
    """
    Calculate pairwise coordinate differences between all locations

    For example:

    [[0,0], [1,1], [2,2]] ->

    [[[0,0], [1, 1], [2, 2]],
     [[-1,-1], [0, 0], [1, 1]],
     [[-2,-2], [-1, -1], [0, 0]]]

    :param locations: np.ndarray of shape (N, 2), where N is the
    number of coordinate points
    :return: np.ndarray of shape (N, N, 2)
    """
    return (locations[None] - locations[:, None]).astype(int)


def build_basis_indices(locations, tissue_mask):
    """
    Creates 8 sets of basis functions: north, south, east, west, for in- and out-tissue.
    Each basis is how far the 2nd element is from the first element.

    Output is two matrices:

    (basis index matrix, basis mask matrix)

    The basis index matrix has the following pseudo-code definition

    for location_i in locations:
        for location_j in locations:
            [number non_tissue spots north of location_i up until location_j,
             number non_tissue spots south of location_i up until location_j,
             number non_tissue spots east of location_i up until location_j,
             number non_tissue spots west of location_i up until location_j,
             number tissue spots north of location_i up until location_j,
             number tissue spots south of location_i up until location_j,
             number tissue spots east of location_i up until location_j,
             number tissue spots west of location_i up until location_j]

    The mask index has the following pseudo-code definition:

    for location_i in locations:
        for location_j in locations:
            if location_i != location_j:
                [true if location_i is >= location_j on first dimension else false,
                 true if location_i is < location_j on first dimension else false,
                 true if location_i is >= location_j on second dimension else false,
                 true if location_i is < location_j on second dimension else false,
                 true if location_i is >= location_j on first dimension else false,
                 true if location_i is < location_j on first dimension else false,
                 true if location_i is >= location_j on second dimension else false,
                 true if location_i is < location_j on second dimension else false]
            else if location_i == location_j: 
                [False]*8

    :param locations:
    :param tissue_mask:
    :return: (basis_idxs, basis_mask)
    """
    NORTH = 0
    SOUTH = 1
    EAST = 2
    WEST = 3
    pairwise_coordinate_differences = calculate_pairwise_coordinate_differences(locations)

    basis_idxs = np.zeros((locations.shape[0], locations.shape[0], 8), dtype=int)
    basis_mask = np.zeros((locations.shape[0], locations.shape[0], 8), dtype=bool)

    tissue_grid = tissue_mask_to_grid(tissue_mask, locations)

    for location_index, location in enumerate(locations):
        # North
        for j in np.flatnonzero(pairwise_coordinate_differences[location_index, :, 0] >= 0):
            # Calculate the amount of in-tissue spots from the 1st to 2nd element going north
            basis_idxs[location_index, j, NORTH + 4] = tissue_grid[
                                                       location[0]:location[0] + pairwise_coordinate_differences[
                                                           location_index, j, 0], location[1]].sum()
            basis_mask[location_index, j, NORTH + 4] = True

            basis_idxs[location_index, j, NORTH] = pairwise_coordinate_differences[location_index, j, 0] - basis_idxs[
                location_index, j, NORTH + 4]
            basis_mask[location_index, j, NORTH] = True

        # South
        for j in np.flatnonzero(pairwise_coordinate_differences[location_index, :, 0] < 0):
            # Calculate the amount of in-tissue spots from the 1st to 2nd element going south
            basis_idxs[location_index, j, SOUTH + 4] = tissue_grid[location[0] + pairwise_coordinate_differences[
                location_index, j, 0]:location[0], location[1]].sum()
            basis_mask[location_index, j, SOUTH + 4] = True

            basis_idxs[location_index, j, SOUTH] = -pairwise_coordinate_differences[location_index, j, 0] - basis_idxs[
                location_index, j, SOUTH + 4]
            basis_mask[location_index, j, SOUTH] = True

        # East
        for j in np.flatnonzero(pairwise_coordinate_differences[location_index, :, 1] >= 0):
            # Calculate the amount of in-tissue spots from the 1st to 2nd element going east
            basis_idxs[location_index, j, EAST + 4] = tissue_grid[location[0],
                                                      location[1]:location[1] + pairwise_coordinate_differences[
                                                          location_index, j, 1]].sum()
            basis_mask[location_index, j, EAST + 4] = True

            basis_idxs[location_index, j, EAST] = pairwise_coordinate_differences[location_index, j, 1] - basis_idxs[
                location_index, j, EAST + 4]
            basis_mask[location_index, j, EAST] = True

        # West
        for j in np.flatnonzero(pairwise_coordinate_differences[location_index, :, 1] < 0):
            # Calculate the amount of in-tissue spots from the 1st to 2nd element going west
            basis_idxs[location_index, j, WEST + 4] = tissue_grid[location[0],
                                                      location[1] + pairwise_coordinate_differences[
                                                          location_index, j, 1]:location[1]].sum()
            basis_mask[location_index, j, WEST + 4] = True

            # Calculate the amount of out-tissue
            basis_idxs[location_index, j, WEST] = -pairwise_coordinate_differences[location_index, j, 1] - basis_idxs[
                location_index, j, WEST + 4]
            basis_mask[location_index, j, WEST] = True

        # Treat the local spot specially
        basis_mask[location_index, location_index] = False

    return basis_idxs, basis_mask


def softplus(x):
    return np.log1p(np.exp(-np.abs(x))) + np.maximum(x, 0)


def weights_from_basis(basis_functions, basis_idxs, basis_mask, tissue_mask, local_weight):
    W = np.sum([basis_functions[d, basis_idxs[:, :, d]] * basis_mask[:, :, d] for d in range(basis_functions.shape[0])],
               axis=0)
    W[np.arange(tissue_mask.shape[0]), np.arange(tissue_mask.shape[0])] += local_weight * tissue_mask.astype(float)
    Weights = stable_softmax(W, axis=0)
    return Weights


BASIS_FUNCTION_INITIALIZATION_VALUE = -3
BASIS_FUNCTION_OPTIMIZATION_MAX_ITERATIONS = 100


def fit_basis_functions(Reads, tissue_mask, Rates, global_rates, basis_idxs, basis_mask, lam=0, local_weight=100,
                        x_init=None):
    # local_weight = 100
    N = Reads.sum(axis=0)
    t_Y = torch.Tensor(Reads.T)
    t_Rates = torch.Tensor(Rates)
    t_Beta0 = torch.Tensor(global_rates)
    t_basis_idxs = torch.LongTensor(basis_idxs)
    t_basis_mask = torch.Tensor(basis_mask)
    t_local_mask = torch.Tensor(tissue_mask.astype(float))
    t_local_idxs = torch.LongTensor(np.arange(Reads.shape[0]))
    sm = Softmax(dim=0)
    sp = Softplus()

    # We have a set of basis functions with mappings from spots to locations in each basis
    # The shape of this tensor is (N of functions x max number of steps between spots)
    # Because we use a function for each cardinal direction in-tissue, and a function for each
    # cardinal direction out of tissue, the first dimension will always be 8.
    # The second dimension depends on the shape of the reads matrix and the tissue mask,
    # in most cases it will be equal to the longest dimension of the reads array
    basis_shape = (basis_idxs.shape[2], basis_idxs.max() + 1)
    t_reverse = torch.LongTensor(np.arange(basis_shape[1])[::-1].copy())

    if x_init is None:
        x_init = np.full(basis_shape, BASIS_FUNCTION_INITIALIZATION_VALUE)  # TODO why -3 ??
        # x_init = (np.median(Reads, axis=0), )
        # x_init = np.concatenate([x_init[0], x_init[1].reshape(-1)])
        # print(x_init)

    def loss(t_Betas):
        t_Betas = sp(t_Betas)
        # t_Beta0, t_Betas = Betas[:Reads.shape[1]], Betas[Reads.shape[1]:]
        t_Betas = t_Betas.reshape(basis_shape)

        # Exponentiate and sum each basis element from N down to the current entry j for each j
        t_Basis = t_Betas[:, t_reverse].cumsum(dim=1)[:, t_reverse]

        # Add all the basis values for this spot
        W = torch.sum(
            torch.stack([t_Basis[d, t_basis_idxs[:, :, d]] * t_basis_mask[:, :, d] for d in range(basis_shape[0])],
                        dim=0), dim=0)

        # Set the value of each local spot to 1
        W[t_local_idxs, t_local_idxs] += local_weight * t_local_mask

        # Normalize across target spots to get a probability
        t_Weights = sm(W)

        # Rate for each spot is bleed prob * spot rate plus the global read prob
        t_Mu = (t_Rates[None] * t_Weights[..., None]).sum(dim=1) + t_Beta0[None]

        # print(t_Basis.data.numpy()[:,:15])

        # Calculate the negative log-likelihood of the data
        L = -torch.stack(
            [Multinomial(total_count=int(N[i]), probs=t_Mu[:, i]).log_prob(t_Y[i]) for i in range(Reads.shape[1])],
            dim=0).mean()

        if lam > 0:
            # Apply a fused lasso penalty to enforce piecewise linear curves
            L += lam * (t_Betas[:, 1:] - t_Betas[:, :-1]).abs().mean()

        # print('Before L2:', L)
        # Add a tiny bit of ridge penalty
        L += 1e-1 * (t_Basis ** 2).sum()
        # print('After L2:', L)

        return L

    # Optimize using a 2nd order method with autograd for gradient calculation. Amazing times we live in.
    res = minimize(loss, x_init,
                   method='L-BFGS-B',
                   backend='torch',
                   options={'maxiter': BASIS_FUNCTION_OPTIMIZATION_MAX_ITERATIONS})

    optimized_betas = softplus(res.x)
    basis_functions = optimized_betas.reshape(basis_shape)[:, ::-1].cumsum(axis=1)[:, ::-1]

    Weights = weights_from_basis(basis_functions, basis_idxs, basis_mask, tissue_mask, local_weight)
    return basis_functions, Weights, res


def rates_from_raw(x, tissue_mask, Reads_shape):
    Rates = np.zeros(Reads_shape)
    global_rates = softplus(x[:Reads_shape[1]])
    Rates[tissue_mask] = softplus(x[Reads_shape[1]:]).reshape(tissue_mask.sum(), Reads_shape[1])
    return global_rates, Rates


RATE_INITIALIZATION_FACTOR = 1.1


def fit_spot_rates(Reads, tissue_mask, Weights, x_init=None):
    # Filter down the weights to only the nonzero rates
    Weights = Weights[:, tissue_mask]
    n_Rates = tissue_mask.sum()

    N = Reads.sum(axis=0)
    t_Y = torch.Tensor(Reads.T)
    # t_Beta0 = torch.Tensor(global_rates)
    t_Weights = torch.Tensor(Weights)
    sp = Softplus()

    if x_init is None:
        x_init = np.concatenate(
            [np.median(Reads, axis=0),
             np.copy(Reads[tissue_mask].reshape(-1) * RATE_INITIALIZATION_FACTOR).clip(1e-2, None)])

    def loss(t_Rates):
        t_Rates = sp(t_Rates)
        t_Beta0 = t_Rates[:Reads.shape[1]]
        t_Rates = t_Rates[Reads.shape[1]:]
        t_Rates = t_Rates.reshape(n_Rates, Reads.shape[1])
        Mu = (t_Rates[None] * t_Weights[..., None]).sum(dim=1) + t_Beta0[None]

        # Calculate the negative log-likelihood of the data
        L = -torch.stack(
            [Multinomial(total_count=int(N[i]), probs=Mu[:, i]).log_prob(t_Y[i]) for i in range(Reads.shape[1])],
            dim=0).mean()

        # Add a small amount of L2 penalty to reduce variance between spots
        # print('Rates loss before L2:', L)
        L += 1e-1 * (t_Rates ** 2).mean()
        # print(Mu.data.numpy()[tissue_mask][:10])
        # print(t_Beta0)
        # print(L)
        # print('Rates loss after L2:', L)

        return L

    # Optimize using a 2nd order method with autograd for gradient calculation. Amazing times we live in.
    res = minimize(loss, x_init, method='L-BFGS-B', backend='torch')

    global_rates, Rates = rates_from_raw(res.x, tissue_mask, Reads.shape)

    return global_rates, Rates, res


def decontaminate_spots(
        Reads,
        tissue_mask,
        basis_idxs,
        basis_mask,
        n_top=10,
        rel_tol=1e-4,
        max_steps=5,
        local_weight=15,
        basis_init=None,
        Rates_init=None):
    # Handle case where n_top is larger than the number of genes in the experiment
    n_top = min(n_top, Reads.shape[1])

    if Rates_init is None:
        # Initialize the rates to be the local observed reads
        Rates = np.copy(Reads[:, :n_top] * tissue_mask[:, None] * RATE_INITIALIZATION_FACTOR).clip(1e-2, None)
        global_rates = np.median(Reads[:, :n_top], axis=0)
    else:
        global_rates, Rates = rates_from_raw(Rates_init, tissue_mask, (Reads.shape[0], n_top))

    print(f'Fitting basis functions to first {n_top} genes')
    for step in range(max_steps):
        print(f'\nStep {step + 1}/{max_steps}')

        basis_functions, Weights, res = fit_basis_functions(Reads[:, :n_top], tissue_mask, Rates, global_rates,
                                                            basis_idxs, basis_mask,
                                                            lam=0, local_weight=local_weight, x_init=basis_init)
        basis_init = res.x

        global_rates, Rates, res = fit_spot_rates(Reads[:, :n_top], tissue_mask, Weights, x_init=Rates_init)
        Rates_init = res.x
        loss = res.fun

        print(f'\tLoss: {loss:.2f}')

    Rates = np.zeros(Reads.shape)
    global_rates = np.zeros(Reads.shape[1])
    for g in range(Reads.shape[1]):
        print(f'\nGene {g + 1}/{Reads.shape[1]}')
        global_rates[g], Rates[:, g:g + 1], res = fit_spot_rates(Reads[:, g:g + 1], tissue_mask, Weights, x_init=None)

    return global_rates, Rates, basis_functions, Weights, basis_init, Rates_init


def select_local_weight(reads, tissue_mask, basis_idxs, basis_mask,
                        min_weight=1, max_weight=100, n_weights=11, test_pct=0.2, n_top=10):
    reads = reads[:, :n_top]

    # Build the candidate grid
    # weight_grid = np.exp(np.linspace(np.log(min_weight), np.log(max_weight), n_weights)) # Log-linear grid
    weight_grid = np.linspace(min_weight, max_weight, n_weights)  # Linear grid

    # Hold out some non-tissue spots
    n_test = int(np.ceil((~tissue_mask).sum() * test_pct))
    test_idxs = np.random.choice(np.where(~tissue_mask)[0], size=n_test, replace=False)
    test_mask = np.zeros(reads.shape[0], dtype=bool)
    test_mask[test_idxs] = True
    train = (reads[~test_mask], tissue_mask[~test_mask], np.array(basis_idxs[~test_mask][:, ~test_mask]),
             np.array(basis_mask[~test_mask][:, ~test_mask]))
    test = (reads[test_mask], tissue_mask[test_mask], np.array(basis_idxs[test_mask][:, test_mask]),
            np.array(basis_mask[test_mask][:, test_mask]))

    N = reads[test_mask].sum(axis=0)
    losses = np.zeros(n_weights)
    basis_init, Rates_init = None, None
    best_inits = None
    for widx, local_weight in enumerate(weight_grid):
        res = decontaminate_spots(
            train[0],
            train[1],
            train[2],
            train[3],
            local_weight=local_weight,
            basis_init=basis_init,
            Rates_init=Rates_init,
            n_top=n_top)
        global_rates, train_Rates, basis_functions, Weights, basis_init, Rates_init = res

        # Reconstruct the weights and rates for the full dataset
        Weights = weights_from_basis(basis_functions, basis_idxs, basis_mask, tissue_mask, local_weight)
        Rates = np.zeros(reads.shape)
        Rates[~test_mask] = train_Rates

        # Now calculate the test-set-specific probabilities
        Mu = (Rates[None] * Weights[..., None]).sum(axis=1) + global_rates[None]
        Mu = Mu[test_mask]
        Mu = Mu / Mu.sum(axis=0, keepdims=True)
        L = -np.mean([multinomial.logpmf(reads[test_mask, i], N[i], Mu[:, i]) for i in range(reads.shape[1])])

        losses[widx] = L
        for i in range(widx + 1):
            print(f'{i}. local_weight={weight_grid[i]} loss={losses[i]:.2f}')
        print()

        if np.argmin(losses[:widx + 1]) == widx:
            best_inits = (basis_init, Rates_init)

    best = weight_grid[np.argmin(losses)]
    print(f'Best: {best}')

    best_delta = weight_grid[np.argmax(losses[1:] - losses[:-1]) + 1]
    print(f'Best by delta rule: {best_delta}')

    return best, best_delta, losses, weight_grid, best_inits


def has_non_tissue_spots(dataset: data.SpatialExpressionDataset) -> bool:
    return not np.all(dataset.tissue_mask)


def get_suggested_initial_local_weight(dataset: data.SpatialExpressionDataset) -> float:
    return math.sqrt(dataset.tissue_mask.sum())


def plot_basis_functions(basis_functions, output_dir):
    print('Plotting')
    basis_types = ['Out-Tissue', 'In-Tissue']
    basis_names = ['North', 'South', 'West', 'East']

    labels = [(d + t) for t in basis_types for d in basis_names]

    for d in range(basis_functions.shape[0]):
        plt.plot(np.arange(basis_functions.shape[1]), basis_functions[d], label=labels[d])
    plt.xlabel('Distance along cardinal direction')
    plt.ylabel('Relative bleed probability')
    plt.legend(loc='upper right')
    plt.savefig(os.path.join(output_dir, 'basis-functions.pdf'), bbox_inches='tight')
    plt.close()


def plot_bleed_vectors(locations,
                       gene_name,
                       gene_idx,
                       tissue_mask,
                       rates,
                       weights,
                       output_dir,
                       output_format: str = 'pdf'
                       ):
    # Plot the general directionality of where reads come from in each spot
    Contributions = (rates[None, :, gene_idx] * weights)
    Directions = locations[None] - locations[:, None]
    Vectors = (Directions * Contributions[..., None]).mean(axis=1)
    Vectors = Vectors / np.abs(Vectors).max(axis=0, keepdims=True)  # Normalize everything to show relative bleed

    tissue_matrix = imshow_matrix(tissue_mask, locations)
    im = plt.imshow(tissue_matrix, cmap='viridis', vmin=-1)

    # get the colors of the values, according to the
    # colormap used by imshow
    colors = [im.cmap(im.norm(value)) for value in np.unique(tissue_matrix.flatten())]
    # create a patch (proxy artist) for every color
    patches = [mpatches.Patch(color=colors[0], label='Out of tissue'),
               mpatches.Patch(color=colors[1], label='In tissue')
               ]
    # put those patched as legend-handles into the legend
    plt.legend(handles=patches, bbox_to_anchor=(1.05, 1), loc=2, borderaxespad=0.)

    for i, ((y, x), (dy, dx)) in enumerate(zip(locations, Vectors)):
        plt.arrow(x, y, dx, dy, width=0.1 * np.sqrt(dx ** 2 + dy ** 2), head_width=0.2 * np.sqrt(dx ** 2 + dy ** 2),
                  color='black')

    plt.savefig(os.path.join(output_dir, f'bleed-vectors-{gene_name}.{output_format}'), bbox_inches='tight')
    plt.close()


def plot_before_after_cleanup(
        before_correction: data.SpatialExpressionDataset,
        after_correction: data.SpatialExpressionDataset,
        gene: str,
        output_dir: str,
        output_format: str = 'pdf',
        cmap='jet',
        x_y_swap=False,
        invert=[0, 0]):
    gene_idx_before = np.argwhere(before_correction.gene_names == gene)[0][0]
    gene_idx_after = np.argwhere(after_correction.gene_names == gene)[0][0]

    after_correction_counts = after_correction.raw_counts.copy()

    after_correction_counts[~after_correction.tissue_mask] = np.nan

    # plot
    plot_data = np.vstack(
        [before_correction.raw_counts[:, gene_idx_before], after_correction_counts[:, gene_idx_after]])
    plot_titles = ['Raw Reads', 'Corrected Reads']
    v_min = np.nanpercentile(plot_data, 5, axis=1)
    v_max = np.nanpercentile(plot_data, 95, axis=1)
    if before_correction.layout is data.Layout.HEX:
        marker = 'H'
        size = 5
    else:
        marker = 's'
        size = 10

    plotting.st_plot(
        plot_data[:, None],
        before_correction.positions,
        unit_dist=size,
        cmap=cmap,
        layout=marker,
        x_y_swap=x_y_swap,
        invert=invert,
        v_min=v_min,
        v_max=v_max,
        subtitles=plot_titles,
        name='{}_bleeding_plot'.format(gene),
        plot_format=output_format,
        save=output_dir)


def plot_bleeding(before_correction: data.SpatialExpressionDataset,
                  after_correction: data.SpatialExpressionDataset,
                  gene: str,
                  output_dir: str,
                  output_format: str = 'pdf',
                  cmap='jet',
                  x_y_swap=False,
                  invert=[0, 0]):
    """
    Plot the raw reads, effective reads, and bleeding (if there is any) of a given gene
    where gene can be selected either by gene name or gene index
    """
    gene_idx = np.argwhere(before_correction.gene_names == gene)[0][0]

    # load raw reads
    raw_count = before_correction.raw_counts[:, gene_idx]
    pos = before_correction.positions
    raw_filtered_align = (before_correction.reads[:, gene_idx] == after_correction.reads[:, gene_idx]).sum()
    # determine if any bleeding filtering is performed
    if raw_filtered_align == before_correction.n_spot_in:
        logger.info('\t no bleeding filtering performed')
    # calculate bleeding ratio
    all_counts = before_correction.raw_counts.sum()
    tissue_counts = after_correction.reads.sum()
    bleed_ratio = 1 - tissue_counts / all_counts
    logger.info('\t {:.3f}% bleeds out'.format(bleed_ratio * 100))

    # plot
    plot_intissue = np.ones_like(raw_count) * np.nan
    plot_intissue[before_correction.tissue_mask] = after_correction.reads[:, gene_idx]
    plot_outside = raw_count.copy().astype(float)
    plot_outside[before_correction.tissue_mask] = np.nan
    if bleed_ratio == 0:
        plot_data = np.vstack([raw_count, plot_intissue])
        plot_titles = ['Raw Reads', 'Reads']
    else:
        plot_data = np.vstack([raw_count, plot_intissue, plot_outside])
        plot_titles = ['Raw Reads', 'Reads', 'Bleeding']
    v_min = np.nanpercentile(plot_data, 5, axis=1)
    v_max = np.nanpercentile(plot_data, 95, axis=1)

    if before_correction.layout is data.Layout.HEX:
        marker = 'H'
        size = 5
    else:
        marker = 's'
        size = 10

    logger.info(plot_data.shape)
    plotting.st_plot(
        plot_data[:, None],
        pos,
        unit_dist=size,
        cmap=cmap,
        layout=marker,
        x_y_swap=x_y_swap,
        invert=invert,
        v_min=v_min,
        v_max=v_max,
        subtitles=plot_titles,
        name='{}_bleeding_plot'.format(gene),
        plot_format=output_format,
        save=output_dir)


def clean_bleed(dataset: data.SpatialExpressionDataset,
                n_top: int,
                local_weight: Optional[int] = None,
                max_steps: int = 5) -> (data.SpatialExpressionDataset, data.BleedCorrectionResult):
    """
    :param dataset: SpatialExpressionDataset
    :param n_top: Number of genes to use for bleed correction.
                  Will use the top n genes by standard deviation for building basis functions.
    :param local_weight: Tuning parameter (optional, a reasonable value will be chosen if not provided)
    :param max_steps: Number of Expectation Maximization iterations to use.
    :return: Tuple of (SpatialExpressionDataset, BleedCorrectionResult), the SpatialExpressionDataset
             returned will contain the bleed corrected read counts.
    """
    if not has_non_tissue_spots(dataset):
        raise RuntimeError('Cannot run clean bleed without non-tissue spots.')

    if local_weight is None:
        local_weight = get_suggested_initial_local_weight(dataset)

    basis_idxs, basis_mask = build_basis_indices(dataset.positions.T, dataset.tissue_mask)

    n_top = min(n_top, dataset.n_gene)

    global_rates, fit_rates, basis_functions, weights, _, _ = decontaminate_spots(
        dataset.raw_counts,
        dataset.tissue_mask,
        basis_idxs,
        basis_mask,
        n_top=n_top,
        max_steps=max_steps,
        local_weight=local_weight)

    corrected_reads = np.round(
        fit_rates / fit_rates.sum(axis=0, keepdims=True) * dataset.raw_counts.sum(axis=0, keepdims=True))

    cleaned_dataset = data.SpatialExpressionDataset(
        raw_counts=corrected_reads,
        tissue_mask=dataset.tissue_mask,
        positions=dataset.positions,
        gene_names=dataset.gene_names,
        layout=dataset.layout
    )

    bleed_correction_result = data.BleedCorrectionResult(
        global_rates=global_rates,
        basis_functions=basis_functions,
        weights=weights,
        corrected_reads=corrected_reads
    )

    return cleaned_dataset, bleed_correction_result


def create_top_n_gene_bleeding_plots(
        dataset: data.SpatialExpressionDataset,
        corrected_dataset: data.SpatialExpressionDataset,
        bleed_result: data.BleedCorrectionResult,
        output_dir: str,
        output_format: str = 'pdf',
        n_genes: int = 10):
    top_gene_names = utils.get_top_gene_names_by_stddev(
        reads=corrected_dataset.reads,
        gene_names=corrected_dataset.gene_names,
        n_genes=n_genes)

    for gene_name in top_gene_names:
        plot_before_after_cleanup(
            before_correction=dataset,
            after_correction=corrected_dataset,
            gene=gene_name,
            output_dir=output_dir,
            output_format=output_format)

        plot_bleed_vectors(
            locations=corrected_dataset.positions.T,
            gene_name=gene_name,
            gene_idx=np.argwhere(corrected_dataset.gene_names == gene_name)[0][0],
            tissue_mask=corrected_dataset.tissue_mask,
            weights=bleed_result.weights,
            rates=np.copy(dataset.raw_counts) * dataset.tissue_mask[:, None],
            output_dir=output_dir,
            output_format=output_format)
