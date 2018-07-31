"""
Trainer class. Handles training and validation
"""

from KITTIDataset import KITTIDataset
from Model import DeepVO
import numpy as np
import os
import sys
import torch
import torch.nn as nn
import torch.optim as optim
from tqdm import tqdm, trange


class Trainer():

	def __init__(self, args, epoch, model, train_set, val_set, loss_fn, optimizer, scheduler = None, \
		scaleFactor = 1., gradClip = None, weightRegularizer = None):


		# Commandline arguments
		self.args = args

		# Maximum number of epochs to train for
		self.maxEpochs = self.args.nepochs
		# Current epoch (initally set to -1)
		self.curEpoch = epoch

		# Model to train
		self.model = model

		# Train and validataion sets (Dataset objects)
		self.train_set = train_set
		self.val_set = val_set

		# Loss function
		self.loss_fn = nn.MSELoss(reduction = 'sum')

		# Variables to hold loss
		self.loss_rot = torch.zeros(1, dtype = torch.float32).cuda()
		self.loss_trans = torch.zeros(1, dtype = torch.float32).cuda()
		self.loss = torch.zeros(1, dtype = torch.float32).cuda()

		# Optimizer
		self.optimizer = optimizer

		# Scheduler
		self.scheduler = scheduler

		# Multiplier for the rotation loss term
		self.scaleFactor = scaleFactor

		# Multiplier for weight regularizer
		self.weightRegularizer = weightRegularizer

		# Flush gradient buffers before beginning training
		self.model.zero_grad()

		# Keep track of number of iters (useful for tensorboardX visualization)
		self.iters = 0


	# Train for one epoch
	def train(self):

		# Switch model to train mode
		self.model.train()

		# Check if maxEpochs have elapsed
		if self.curEpoch >= self.maxEpochs:
			print('Max epochs elapsed! Returning ...')
			return

		# Increment iters
		self.iters += 1

		# Variables to store stats
		rotLosses = []
		transLosses = []
		totalLosses = []
		rotLoss_seq = []
		transLoss_seq = []
		totalLoss_seq = []

		# Handle debug mode here
		if self.args.debug is True:
			numTrainIters = self.args.debugIters
		else:
			numTrainIters = len(self.train_set)

		# Initialize a variable to hold the number of sampes in the current batch
		# Here, 'batch' refers to the length of a subsequence that can be processed
		# before performing a 'detach' operation
		elapsedBatches = 0

		# Run a pass of the dataset
		for i in trange(numTrainIters):

			# Get the next frame
			inp, rot_gt, trans_gt, _, _, _, endOfSeq = self.train_set[i]

			# Feed it through the model
			rot_pred, trans_pred = self.model.forward(inp)

			# Compute loss
			self.loss_rot += self.scaleFactor * self.loss_fn(rot_pred, rot_gt)
			self.loss_trans += self.loss_fn(trans_pred, trans_gt)
			self.loss += sum([self.scaleFactor * self.loss_fn(rot_pred, rot_gt), \
				self.loss_fn(trans_pred, trans_gt)])

			# Store losses (for further analysis)
			curloss_rot = (self.scaleFactor * self.loss_fn(rot_pred, rot_gt)).detach().cpu().numpy()
			curloss_trans = (self.loss_fn(trans_pred, trans_gt)).detach().cpu().numpy()
			rotLosses.append(curloss_rot)
			transLosses.append(curloss_trans)
			totalLosses.append(curloss_rot + curloss_trans)
			rotLoss_seq.append(curloss_rot)
			transLoss_seq.append(curloss_trans)
			totalLoss_seq.append(curloss_rot + curloss_trans)

			# Handle debug mode here. Force execute the below if statement in the
			# last debug iteration
			if self.args.debug is True:
				if i == numTrainIters - 1:
					endOfSeq = True

			elapsedBatches += 1
			
			# if endOfSeq is True:
			if elapsedBatches >= self.args.trainBatch or endOfSeq is True:

				elapsedBatches = 0
				
				if self.weightRegularizer is not None:
					# Regularization for network weights
					l2_reg = None
					for W in self.model.parameters():
						if l2_reg is None:
							l2_reg = W.norm(2)
						else:
							l2_reg = l2_reg + W.norm(2)
					self.loss = sum([self.weightRegularizer * l2_reg, self.loss])

				# Print stats
				tqdm.write('Rot Loss: ' + str(np.mean(rotLoss_seq)) + ' Trans Loss: ' + \
					str(np.mean(transLoss_seq)), file = sys.stdout)
				tqdm.write('Total Loss: ' + str(np.mean(totalLoss_seq)), file = sys.stdout)
				rotLoss_seq = []
				transLoss_seq = []
				totalLoss_seq = []

				# Compute gradients
				self.loss.backward()

				# Perform gradient clipping, if enabled
				if self.args.gradClip is not None:
					torch.nn.utils.clip_grad_norm_(self.model.parameters(), self.args.gradClip)

				# Update parameters
				self.optimizer.step()

				# Detach LSTM hidden states
				self.model.detach_LSTM_hidden()

				# Reset loss variables
				self.loss_rot = torch.zeros(1, dtype = torch.float32).cuda()
				self.loss_trans = torch.zeros(1, dtype = torch.float32).cuda()
				self.loss = torch.zeros(1, dtype = torch.float32).cuda()

				# Flush gradient buffers for next forward pass
				self.model.zero_grad()

				# If it's the end of sequence, reset hidden states
				if endOfSeq is True:
					self.model.reset_LSTM_hidden()

		# Return loss logs for further analysis
		return rotLosses, transLosses, totalLosses


	# Run one epoch of validation
	def validate(self):

		# Switch model to eval mode
		self.model.eval()

		# Run a pass of the dataset
		traj_pred = None

		# Variables to store stats
		rotLosses = []
		transLosses = []
		totalLosses = []
		rotLoss_seq = []
		transLoss_seq = []
		totalLoss_seq = []

		# Handle debug switch here
		if self.args.debug is True:
			numValIters = self.args.debugIters
		else:
			numValIters = len(self.val_set)

		for i in trange(numValIters):

			# Get the next frame
			inp, rot_gt, trans_gt, seq, frame1, frame2, endOfSeq = self.val_set[i]
			metadata = np.concatenate((np.asarray([seq]), np.asarray([frame1]), np.asarray([frame2])))
			metadata = np.reshape(metadata, (1, 3))

			# Feed it through the model
			rot_pred, trans_pred = self.model.forward(inp)

			if traj_pred is None:
				traj_pred = np.concatenate((metadata, rot_pred.data.cpu().numpy(), \
					trans_pred.data.cpu().numpy()), axis = 1)
			else:
				cur_pred = np.concatenate((metadata, rot_pred.data.cpu().numpy(), \
					trans_pred.data.cpu().numpy()), axis = 1)
				traj_pred = np.concatenate((traj_pred, cur_pred), axis = 0)

			# Compute loss
			self.loss_rot += self.scaleFactor * self.loss_fn(rot_pred, rot_gt)
			self.loss_trans += self.loss_fn(trans_pred, trans_gt)
			self.loss += sum([self.scaleFactor * self.loss_fn(rot_pred, rot_gt), \
				self.loss_fn(trans_pred, trans_gt)])

			# Store losses (for further analysis)
			curloss_rot = (self.scaleFactor * self.loss_fn(rot_pred, rot_gt)).detach().cpu().numpy()
			curloss_trans = (self.loss_fn(trans_pred, trans_gt)).detach().cpu().numpy()
			rotLosses.append(curloss_rot)
			transLosses.append(curloss_trans)
			totalLosses.append(curloss_rot + curloss_trans)
			rotLoss_seq.append(curloss_rot)
			transLoss_seq.append(curloss_trans)
			totalLoss_seq.append(curloss_rot + curloss_trans)

			if endOfSeq is True:

				# Print stats
				tqdm.write('Rot Loss: ' + str(np.mean(rotLoss_seq)) + ' Trans Loss: ' + \
					str(np.mean(transLoss_seq)), file = sys.stdout)
				tqdm.write('Total Loss: ' + str(np.mean(totalLoss_seq)), file = sys.stdout)
				rotLoss_seq = []
				transLoss_seq = []
				totalLoss_seq = []

				# Write predicted trajectory to file
				saveFile = os.path.join(self.args.expDir, 'plots', 'traj', str(seq).zfill(2), \
					'traj_' + str(self.curEpoch).zfill(3) + '.txt')
				np.savetxt(saveFile, traj_pred, newline = '\n')
				
				# Reset variable, to store new trajectory later on
				traj_pred = None
				
				# Detach LSTM hidden states
				self.model.detach_LSTM_hidden()

				# Reset loss variables
				self.loss_rot = torch.zeros(1, dtype = torch.float32).cuda()
				self.loss_trans = torch.zeros(1, dtype = torch.float32).cuda()
				self.loss = torch.zeros(1, dtype = torch.float32).cuda()

		# Return loss logs for further analysis
		return rotLosses, transLosses, totalLosses