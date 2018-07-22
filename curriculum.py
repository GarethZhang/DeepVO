import numpy as np

########################################################################
### Curriculum learning ###
########################################################################

# Function that specifies a set curriculum for the network to learn.
# Presented sequences gradually increase in length.
class Curriculum:

	# Constructor
	def __init__(self, good_loss = 9e-3, min_frames = 5, max_frames = 1095):

		# A loss value that we'll be happy with, and increase sequence size
		self.good_loss = good_loss
		# Min and max sequence lengths
		self.min_frames = min_frames
		self.max_frames = max_frames
		# Initialize current loss value to inf
		self.current_loss = np.inf

		# Current sequence length (this is the variable of interset)
		self.cur_seqlen = min_frames


	# A step through the curriculum. Examine the current loss. If it seems satisfactory, 
	# move ahead and increase sequence length
	def step(self, cur_loss):

		if cur_loss <= self.good_loss:
			self.cur_seqlen += np.random.randint(self.cur_seqlen, int(np.ceil(self.cur_seqlen*1.5)))
			if self.cur_seqlen > max_frames:
				self.cur_seqlen = max_frames