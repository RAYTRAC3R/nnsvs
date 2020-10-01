# coding: utf-8

import torch
from torch import nn
import torch.nn.functional as F

class MDNLayer(nn.Module):
    """ Mixture Density Network layer

    The input maps to the parameters of a Mixture of Gaussians (MoG) probability 
    distribution, where each Gaussian has out_dim dimensions and diagonal covariance.

    Implementation references:
    1. Mixture Density Networks by Mike Dusenberry https://mikedusenberry.com/mixture-density-networks
    2. PRML book https://www.microsoft.com/en-us/research/people/cmbishop/prml-book/
    3. sagelywizard/pytorch-mdn https://github.com/sagelywizard/pytorch-mdn
    4. sksq96/pytorch-mdn https://github.com/sksq96/pytorch-mdn

    Arguments:
        in_dim (int): the number of dimensions in the input
        out_dim (int): the number of dimensions in the output
        num_gaussians (int): the number of mixture component
    Input:
        minibatch (B, max(T), D_in): B is the batch size and max(T) is the max frame lengths
            in this batch, and D_in is in_dim
    Output:
        pi, sigma, mu (B, max(T), G), (B, max(T), G, D_out), (B, max(T), G, D_out): 
            G is num_gaussians and D_out is out_dim.
            pi is a multinomial distribution of the Gaussians(not Softmax-ed). 
            mu and sigma are the mean and the standard deviation of each Gaussian.
    Note: pi is not Softmax-ed due to the numerical stability. If you want to construct whole
        probabilistic density function, you should apply torch.nn.functional.softmax to them first.
    """
    def __init__(self, in_dim, out_dim, num_gaussians=30):
        super(MDNLayer, self).__init__()
        self.in_dim = in_dim
        self.out_dim = out_dim
        self.num_gaussians = num_gaussians

        self.pi = nn.Linear(in_dim, num_gaussians)
        self.sigma = nn.Linear(in_dim, out_dim * num_gaussians)
        self.mu = nn.Linear(in_dim, out_dim * num_gaussians)

    def forward(self, minibatch):
        pi = self.pi(minibatch) 
#        sigma = torch.exp(self.sigma(minibatch))
        sigma = self.sigma(minibatch)
        sigma = sigma.view(len(minibatch), -1, self.num_gaussians, self.out_dim)        
        mu = self.mu(minibatch)
        mu = mu.view(len(minibatch), -1, self.num_gaussians, self.out_dim)
        return pi, sigma, mu

def mdn_loss(pi, sigma, mu, target, reduce=True):
    """Calculates the error, given the MoG parameters and the target.
    The loss is the negative log likelihood of the data given the MoG
    parameters.
    Arguments:
        pi (B, max(T), G): The multinomial distribution of the Gaussians(not Softmax-ed). B is the batch size,
            max(T) is the max frame length in this batch, and G is num_gaussians of class MDNLayer.
        sigma (B, max(T) , G ,D_out): The standard deviation of the Gaussians. D_out is out_dim of class 
            MDNLayer.
        mu (B , max(T), G, D_out): The means of the Gaussians. 
        target (B,max(T), D_out): The target variables.
        reduce: If True, the losses are averaged or summed for each minibatch.
    Returns:
        loss (B): Negative Log Likelihood of Mixture Density Networks.
    """
    # Expand the dim of target as (B,max(T),D_out) -> (B,max(T),1,D_out) -> (B,max(T),G,D_out)
    target = target.unsqueeze(2).expand_as(sigma)

    # Expand the dim of pi as (B,max(T),G) -> (B,max(T),G,1)-> (B,max(T),G,D_out)
    #pi = pi.unsqueeze(3).expand_as(sigma)
    
    # Create gaussians with mean=mu and variance=sigma^2
    dist = torch.distributions.Normal(loc=mu, scale=torch.exp(sigma))

    # Use torch.log_sum_exp instead of the combination of torch.sum and torch.log
    # Please see https://github.com/r9y9/nnsvs/pull/20#discussion_r495514563
    # log p(y|x,w) + log pi
    #loss = dist.log_prob(target) + F.log_softmax(pi, dim=2)
    # (B, max(T), G, D_out) -> (B, max(T), G)
    loss = torch.sum(dist.log_prob(target), dim=3) + F.log_softmax(pi, dim=2)
    
    # Calculate negative log likelihood.
    # (B, max(T), G, D_out) -> (B, max(T), D_out)
    loss = torch.logsumexp(loss, dim=2)

    # Sum along the dimension of target variables to reduce the dim of loss
    # (B, max(T), D_out) -> (B, max(T))
    #loss = torch.sum(loss, dim=2)

    if reduce:
        # (B, max(T)) -> (B)
        return -torch.mean(loss, dim=1)
    else:
        # not averaged (for applying mask later)
        # (B, max(T))
        return -loss
    return 

# from r9y9/wavenet_vocoder/wavenet_vocoder/mixture.py
def to_one_hot(tensor, n, fill_with=1.):
    # we perform one hot encore with respect to the last axis
    one_hot = torch.FloatTensor(tensor.size() + (n,)).zero_()
    if tensor.is_cuda:
        one_hot = one_hot.cuda()
    one_hot.scatter_(len(tensor.size()), tensor.unsqueeze(-1), fill_with)
    return one_hot

def mdn_sample_mode(pi, mu):
    """ Returns the mean of the Gaussian component whose weight coefficient is the largest
    as the most probable predictions.

    Arguments:
        pi (B, max(T), G): The multinomial distribution of the Gaussians(not Softmax-ed). 
            B is the batch size, max(T) is the max frame length in this batch, 
            G is num_gaussians of class MDNLayer.
        mu (B, max(T), G, D_out): The means of the Gaussians. D_out is out_dim of class 
            MDNLayer.
    Returns:
        mode (B, max(T), D_out): The means of the Gaussians whose weight coefficient (pi) is the largest.
    """
    
    batch_size, max_T, num_gaussians , out_dim = mu.shape
    # Get the indexes of the largest pi
    _, max_component = torch.max(pi, dim=2) # (B, max(T))

    # Convert max_component to one_hot manner
    # (B, max(T) -> (B, max(T), G)
    one_hot = to_one_hot(max_component, num_gaussians)

    # Expand the dim of one_hot as (B, max(T), G) -> (B, max(T), G, d_out)
    one_hot = one_hot.unsqueeze(3).expand_as(mu)
    
    # Multply one_hot and sum to get mean(mu) of the Gaussians
    # whose weight coefficient(pi) is the largest.
    #  (B, max(T), G, d_out) -> (B, max(T), d_out)
    max_mu = torch.sum(mu * one_hot, dim=2)

    return max_mu


def mdn_sample(pi, sigma, mu):
    """ Sample from mixture of the Gaussian component whose weight coefficient is the largest
    as the most probable predictions.

    Arguments:
        pi (B, max(T), G): The multinomial distribution of the Gaussians(not Softmax-ed). 
            B is the batch size, max(T) is the max frame length in this batch, 
            G is num_gaussians of class MDNLayer.
        sigma (B, max(T) , G ,D_out): The standard deviation of the Gaussians. D_out is out_dim of class 
            MDNLayer.
        mu (B, max(T), G, D_out): The means of the Gaussians. D_out is out_dim of class 
            MDNLayer.
    Returns:
        sample (B, max(T), D_out): Sample from mixture of the Gaussian component
    """
    batch_size, max_T, num_gaussians , out_dim = mu.shape
    # Get the indexes of the largest pi
    _, max_component = torch.max(pi, dim=2) # (B, max(T))

    # Convert max_component to one_hot manner
    # (B, max(T) -> (B, max(T), G)
    one_hot = to_one_hot(max_component, num_gaussians)

    # Expand the dim of one_hot as  (B, max(T), G) -> (B, max(T), G, d_out)
    one_hot = one_hot.unsqueeze(3).expand_as(mu)

    # Multply one_hot and sum to get mean(mu) and variance(sigma) of the Gaussians
    # whose weight coefficient(pi) is the largest.
    #  (B, max(T), G, d_out) -> (B, max(T), d_out)
    max_mu = torch.sum(mu * one_hot, dim=2)
    max_sigma = torch.sum(sigma * one_hot, dim=2)

    # Create gaussians with mean=max_mu and variance=max_sigma^2
    dist= torch.distributions.Normal(loc=max_mu, scale=torch.exp(max_sigma))

    # Sample from normal distribution
    sample = dist.sample()
    
    return sample
