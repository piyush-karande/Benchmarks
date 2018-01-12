from __future__ import absolute_import
from __future__ import print_function

#import matplotlib
#if 'MACOSX' in matplotlib.get_backend().upper():
#  matplotlib.use('TKAgg')
#import pylab as py
#py.ion() ## Turn on plot visualization

import gzip, pickle
import numpy as np
#from PIL import Image
#import cv2
import keras.backend as K
from keras.layers import Input
from keras.models import Sequential,Model
from keras.layers.core import Flatten, Dense, Dropout, Activation, Reshape
from keras.layers.convolutional import Convolution2D, MaxPooling2D,Convolution1D
#from keras.layers.convolutional import ZeroPadding2D,UpSampling2D,Unpooling2D,perforated_Unpooling2D,DePool2D
from keras.initializers import normal, identity, he_normal,glorot_normal,glorot_uniform,he_uniform
from keras.layers.normalization import BatchNormalization
from keras.regularizers import l2, l1
import threading
try:
    import configparser
except ImportError:
    import ConfigParser as configparser
#from tqdm import *
import re,copy
import os
import sys

file_path = os.path.dirname(os.path.realpath(__file__))
lib_path = os.path.abspath(os.path.join(file_path, '..', 'common'))
sys.path.append(lib_path)
lib_path2 = os.path.abspath(os.path.join(file_path, '..', '..', 'common'))
sys.path.append(lib_path2)

import p2_common

import helper

def common_parser(parser):

    parser.add_argument("--config_file", dest='config_file', type=str,
                        default=os.path.join(file_path, 'p2b1_default_model.txt'),
                        help="specify model configuration file")

    # Parse has been split between arguments that are common with the default neon parser
    # and all the other options
    parser = p2_common.get_default_neon_parse(parser)
    parser = p2_common.get_p2_common_parser(parser)

    # Arguments that are applicable just to p2b1
    parser = p2b1_parser(parser)

    return parser

def p2b1_parser(parser):
    ### Hyperparameters and model save path

#    parser.add_argument("--train", action="store_true",dest="train_bool",default=True,help="Invoke training")
#    parser.add_argument("--evaluate", action="store_true",dest="eval_bool",default=False,help="Use model for inference")
#    parser.add_argument("--home-dir",help="Home Directory",dest="home_dir",type=str,default='.')
    parser.add_argument("--save-dir", help="Save Directory", dest="save_path", type=str, default=None)
    parser.add_argument("--config-file", help="Config File", dest="config_file", type=str,
                        default=os.path.join(file_path, 'p2b1_small_model.txt'))

    parser.add_argument("--model-file", help="Trained Model Pickle File", dest="weight_path", type=str, default=None)
    parser.add_argument("--memo", help="Memo", dest="base_memo", type=str, default=None)
    parser.add_argument("--seed", action="store_true", dest="seed", default=False, help="Random Seed")
    parser.add_argument("--case", help="[Full, Center, CenterZ]", dest="case", type=str, default='CenterZ')
    parser.add_argument("--fig", action="store_true", dest="fig_bool", default=False, help="Generate Prediction Figure")
    parser.add_argument("--data-set",  help="[3k_run16, 3k_run10, 3k_run32]", dest="set_sel",
                        type=str, default="3k_run16")

    parser.add_argument("--conv-AE", action="store_true", dest="conv_bool", default=False,
                        help="Invoke training using 1D Convs for inner AE")

    parser.add_argument("--full-conv-AE", action="store_true", dest="full_conv_bool", default=False,
                        help="Invoke training using fully convolutional NN for inner AE")

    parser.add_argument("--include-type", action="store_true", dest="type_bool", default=False,
                        help="Include molecule type information in desining AE")

    parser.add_argument("--backend", help="Keras Backend", dest="backend", type=str, default='theano')
    #(opts,args)=parser.parse_args()
    return parser


#### Read Config File
def read_config_file(File):
    config=configparser.ConfigParser()
    config.read(File)
    section=config.sections()
    Global_Params={}

    Global_Params['num_hidden']    =eval(config.get(section[0],'num_hidden'))
    Global_Params['batch_size']    =eval(config.get(section[0],'batch_size'))
    Global_Params['learning_rate'] =eval(config.get(section[0],'learning_rate'))
    Global_Params['epochs']        =eval(config.get(section[0],'epochs'))
    Global_Params['weight_decay']  =eval(config.get(section[0],'weight_decay'))
    Global_Params['noise_factor']  =eval(config.get(section[0],'noise_factor'))
    Global_Params['optimizer']     =eval(config.get(section[0],'optimizer'))
    Global_Params['loss']          =eval(config.get(section[0],'loss'))
    Global_Params['activation']    =eval(config.get(section[0],'activation'))
    # note 'cool' is a boolean
    Global_Params['cool']          =config.get(section[0],'cool')

    Global_Params['molecular_epochs']       = eval(config.get(section[0],'molecular_epochs'))
    Global_Params['molecular_num_hidden']   = eval(config.get(section[0],'molecular_num_hidden'))
    Global_Params['molecular_nonlinearity'] = config.get(section[0],'molecular_nonlinearity')
    Global_Params['molecular_nbrs'] = config.get(section[0],'molecular_nbrs')
    Global_Params['drop_prob'] = config.get(section[0],'drop_prob')

    # parse the remaining values
    for k,v in config.items(section[0]):
        if not k in Global_Params:
            Global_Params[k] = eval(v)

    return Global_Params

#### Extra Code #####
def reorder_npfiles(files):
    files1=copy.deepcopy(files)
    for i in range(len(files)):
        inx=map(int,re.findall('\d+',files[i][96:98]))[0]
        files1[inx-1]=files[i]
    return files1

def convert_to_helgi_format(data):
    new_data=np.zeros((data.shape[0],data.shape[1],12,6))
    for i in range(data.shape[0]):
        for j in range(data.shape[1]):
            new_data[i,j,:,:]=np.hstack([data[i,j][0],np.array(12*[list(data[i,j][1])])])
    return new_data

############# Define Data Generators ################
class ImageNoiseDataGenerator(object):
    '''Generate minibatches with
    realtime data augmentation.
    '''
    def __init__(self,corruption_level=0.5):

        self.__dict__.update(locals())
        self.p=corruption_level
        self.lock = threading.Lock()

    def _flow_index(self, N, batch_size=32, shuffle=False, seed=None):
        b = 0
        total_b = 0
        while 1:
            if b == 0:
                if seed is not None:
                    np.random.seed(seed + total_b)

                if shuffle:
                    index_array = np.random.permutation(N)
                else:
                    index_array = np.arange(N)

            current_index = (b * batch_size) % N
            if N >= current_index + batch_size:
                current_batch_size = batch_size
            else:
                current_batch_size = N - current_index

            if current_batch_size == batch_size:
                b += 1
            else:
                b=0
                #b=None

            #if current_index + current_batch_size==N:
            #   b=None
            total_b += 1
            yield index_array[current_index: current_index + current_batch_size], current_index, current_batch_size
            #if b==None:
            #    return

    def flow(self, X, y, batch_size=32, shuffle=False, seed=None):
        assert len(X) == len(y)
        self.X = X
        self.y = y
        self.flow_generator = self._flow_index(X.shape[0], batch_size, shuffle, seed)
        return self

    def __iter__(self):
        # needed if we want to do something like for x,y in data_gen.flow(...):
        return self

    def next(self):
        # for python 2.x
        # Keep under lock only the mechainsem which advance the indexing of each batch
        # see # http://anandology.com/blog/using-iterators-and-generators/
        with self.lock:
            index_array, current_index, current_batch_size = next(self.flow_generator)
        # The transformation of images is not under thread lock so it can be done in parallel
        bX = np.zeros(tuple([current_batch_size] + list(self.X.shape)[1:]))
        for i, j in enumerate(index_array):
            x = self.X[j]
            x = self.insertnoise(x,corruption_level=self.p)
            bX[i] = x
        bY = self.y[index_array]
        return bX, bY

    def __next__(self):
        # for python 3.x
        return self.next()

    def insertnoise(self,x,corruption_level=0.5):
        return np.random.binomial(1,1-corruption_level,x.shape)*x

class autoencoder_preprocess():
    def __init__(self,img_size=(784,),noise_factor=0.):
        self.noise=noise_factor
        self.img_size=img_size
        self.lock = threading.Lock()

    def add_noise(self,X_train):
        ## Add noise to input data
        np.random.seed(100)
        ind=np.where(X_train==0)
        rn=self.noise*np.random.rand(np.shape(ind)[1])
        X_train[ind]=rn
        return X_train

    def renormalize(self,X_train,mu,sigma):
        X_train=(X_train-mu)/sigma
        X_train = X_train.astype("float32")
        return X_train

## get activations for hidden layers of the model
def get_activations(model, layer, X_batch):
    get_activations = K.function([model.layers[0].input, K.learning_phase()], [model.layers[layer].output])
    activations = get_activations([X_batch,0])
    return activations


def get_data(X,case='Full'):
    if case.upper()=='FULL':
        X_train=X.copy().reshape(X.shape[0],np.prod(X.shape[1:]))
    if case.upper()=='CENTER':
        X_train=X.mean(axis=2).reshape(X.shape[0],np.prod(X.mean(axis=2).shape[1:]))
    if case.upper()=='CENTERZ':
        X_train=X.mean(axis=2)[:,:,2].reshape(X.shape[0],np.prod(X.mean(axis=2)[:,:,2].shape[1:]))

    return X_train

class Candle_Train():
    def __init__(self, datagen, model, numpylist,nb_epochs,case='Full',batch_size=32,print_data=True):
        self.numpylist=numpylist
        self.epochs=nb_epochs
        self.case=case
        self.batch_size=batch_size
        self.model=model
        self.datagen=datagen
        self.print_data=print_data

    def train_ac(self):
        epoch_loss=[]
        for e in range(self.epochs):
            file_loss=[]
            for f in self.numpylist:
                if self.print_data:
                    if e==0:
                        print (f)
                X=np.load(f)
                X_train=get_data(X,self.case)
                y_train=X_train.copy()
                imggen=self.datagen.flow(X_train, y_train, batch_size=self.batch_size)
                N_iter=X.shape[0]//self.batch_size

                iter_loss=[]
                for _ in range(N_iter+1):
                    x,y=next(imggen)
                    loss_data=self.model.train_on_batch(x,y)
                    iter_loss.append(loss_data)
                file_loss.append(np.array(iter_loss).mean(axis=0))
            print ('\nLoss on epoch %d:'%e, file_loss[-1])
            epoch_loss.append(np.array(file_loss).mean(axis=0))
        return epoch_loss


class Candle_Molecular_Train():
    def __init__(self, molecular_ammodel, molecular_encoder, numpylist, mnb_epochs, callbacks, save_path='.', batch_size=32, case='Full',
                 print_data=True, epsilon=.064, len_molecular_hidden_layers=1, molecular_nbrs=0,
                 conv_bool=False, full_conv_bool=False, type_bool=False):
        self.numpylist = numpylist
        self.molecular_model = molecular_ammodel
        self.molecular_encoder = molecular_encoder
        self.mb_epochs = mnb_epochs
        self.callbacks = callbacks
        self.case = case
        self.batch_size = batch_size
        self.print_data = print_data
        self.epsilon = epsilon
        self.len_molecular_hidden_layers = len_molecular_hidden_layers
        self.molecular_nbrs = molecular_nbrs
        self.conv_net = conv_bool or full_conv_bool
        self.full_conv_net = full_conv_bool
        self.type_feature = type_bool
        self.save_path = save_path+'/'

    def format_data(self):
        X_all = np.array([])
        nbrs_all = np.array([])
        resnums_all = np.array([])
        for f in self.numpylist[:3]:
            print (f)

            (X, nbrs, resnums) = helper.get_data_arrays(f)

            if not len(X_all):
                X_all = X
                nbrs_all = nbrs
                resnums_all = resnums
            else:
                X_all = np.append(X_all, X, axis=0)
                nbrs_all = np.append(nbrs_all, nbrs, axis=0)
                resnums_all = np.append(resnums_all, resnums, axis=0)

        # normalizing the location coordinates and bond lengths and scale type encoding
        if self.type_feature:
            Xnorm = np.concatenate([X_all[:, :, :, 0:3]/320., X_all[:, :, :, 3:8], X_all[:, :, :, 8:]/10.], axis=3)

        # only consider the location coordinates and bond lengths per molecule
        else:
            Xnorm = np.concatenate([X_all[:, :, :, 0:3]/320., X_all[:, :, :, 8:]/10.], axis=3)

        num_frames = X_all.shape[0]
        input_feature_dim = np.prod(Xnorm.shape[2:])

        xt_all = np.array([])
        yt_all = np.array([])

        for i in range(num_frames):

            if self.conv_net:
                xt = Xnorm[i].reshape(X_all.shape[1], input_feature_dim)
                xt = helper.append_nbrs(xt, nbrs_all[i], self.molecular_nbrs)

                yt = xt.copy()
                xt = xt.reshape(xt.shape[0], 1, xt.shape[1], 1)
                if self.full_conv_net:
                    yt = xt.copy()

            else:
                xt = Xnorm[i].reshape(X_all.shape[1], input_feature_dim)
                xt = helper.append_nbrs(xt, nbrs_all[i], self.molecular_nbrs)

                yt = xt.copy()

            if not len(xt_all):
                xt_all = np.expand_dims(xt, axis=0)
                yt_all = np.expand_dims(yt, axis=0)
            else:
                xt_all = np.append(xt_all, np.expand_dims(xt, axis=0), axis=0)
                yt_all = np.append(yt_all, np.expand_dims(yt, axis=0), axis=0)

        return xt_all, yt_all

    def datagen(self, epoch=0, print_out=1):
        X_all = np.array([])
        nbrs_all = np.array([])
        resnums_all = np.array([])
        files = self.numpylist
    # Training only on few files
        order = range(13, 17)
        # Randomize files after first training epoch
        if epoch:
            order = np.random.permutation(order)

        for f_ind in order:
            if (not epoch) and print_out:
                print (files[f_ind])

            (X, nbrs, resnums) = helper.get_data_arrays(files[f_ind])

            # normalizing the location coordinates and bond lengths and scale type encoding
        # Changed the xyz normalization from 255 to 350
            if self.type_feature:
                Xnorm = np.concatenate([X[:, :, :, 0:3]/320., X[:, :, :, 3:8], X[:, :, :, 8:]/10.], axis=3)

            # only consider the location coordinates and bond lengths per molecule
            else:
                Xnorm = np.concatenate([X[:, :, :, 0:3]/320., X[:, :, :, 8:]/10.], axis=3)

            num_frames = X.shape[0]
            input_feature_dim = np.prod(Xnorm.shape[2:])

            xt_all = np.array([])
            yt_all = np.array([])

            for i in range(num_frames):

                if self.conv_net:
                    xt = Xnorm[i]
                    xt = helper.append_nbrs_relative(xt, nbrs[i], self.molecular_nbrs)

                    yt = xt.copy()
                    xt = xt.reshape(xt.shape[0], 1, xt.shape[1], 1)
                    if self.full_conv_net:
                        yt = xt.copy()

                else:
                    xt = Xnorm[i].reshape(X.shape[1], input_feature_dim)
                    xt = helper.append_nbrs(xt, nbrs[i], self.molecular_nbrs)

                    yt = xt.copy()

                if not len(xt_all):
                    xt_all = np.expand_dims(xt, axis=0)
                    yt_all = np.expand_dims(yt, axis=0)
                else:
                    xt_all = np.append(xt_all, np.expand_dims(xt, axis=0), axis=0)
                    yt_all = np.append(yt_all, np.expand_dims(yt, axis=0), axis=0)

            yield files[f_ind], xt_all, yt_all

        return

    def train_ac(self):

        for i in range(self.mb_epochs):
            print ("\nTraining epoch: {:d}\n".format(i))

            frame_loss = []
            frame_mse = []

            os.makedirs(self.save_path+'/epoch_'+str(i))
            current_path = self.save_path+'epoch_'+str(i)
            model_weight_file = '%s/%s.hdf5' % (current_path, 'model_weights')
            encoder_weight_file = '%s/%s.hdf5' % (current_path, 'encoder_weights')

            for curr_file, xt_all, yt_all in self.datagen(i):
                for frame in range(len(xt_all)):

                    history = self.molecular_model.fit(xt_all[frame], yt_all[frame], epochs=1,
                                                       batch_size=self.batch_size, callbacks=self.callbacks[:2],
                                                       verbose=0)
                    frame_loss.append(history.history['loss'])
                    frame_mse.append(history.history['mean_squared_error'])

                    if not frame % 20:
                        print ("Frame: {0:d}, Current history:\nLoss: {1:3.5f}\tMSE: {2:3.5f}\n"
                               .format(frame, history.history['loss'][0], history.history['mean_squared_error'][0]))

                        # Update weights filed every few frames
                        self.molecular_model.save_weights(model_weight_file)
            self.molecular_encoder.save_weights(encoder_weight_file)

            # save Loss and mse
            print ("\nSaving loss and mse after current epoch... \n")
            np.save(current_path+'/loss.npy', frame_loss)
            np.save(current_path+'/mse.npy', frame_mse)

            # Update weights file
            self.molecular_model.save_weights(model_weight_file)
            self.molecular_encoder.save_weights(encoder_weight_file)

            print ("\nSaving latent space output for current epoch... \n")
            for curr_file, xt_all, yt_all in self.datagen(0, 0):
                XP = []
                for frame in range(len(xt_all)):
                    # get latent space activation output, +1 to incorporate the flatten layer
                    # yp = get_activations(self.molecular_model, self.len_molecular_hidden_layers + 1, xt_all[frame])
                    yp = self.molecular_encoder.predict(xt_all[frame], batch_size=self.batch_size)
                    XP.append(yp)

                XP = np.array(XP)
                fout = current_path+'/'+curr_file.split('/')[-1].split('.npz')[0]+'_AE'+'_Include%s' % self.type_feature+'_Conv%s' % self.conv_net+'.npy'
                print (fout)
                np.save(fout, XP)

        return frame_loss, frame_mse


class Candle_Composite_Train():
    def __init__(self, datagen, model, molecular_ammodel, numpylist,mnb_epochs,nb_epochs,callbacks,save_path='.', batch_size=32,case='Full',print_data=True,scale_factor=1,epsilon=.064,len_molecular_hidden_layers=1,molecular_nbrs=0,conv_bool=False,type_bool=False):
        self.numpylist=numpylist
        self.molecular_model=molecular_ammodel
        self.mb_epochs=mnb_epochs
        self.epochs=nb_epochs
        self.callbacks=callbacks
        self.case=case
        self.batch_size=batch_size
        self.model=model
        self.datagen=datagen
        self.print_data=print_data
        self.scale_factor=scale_factor
        self.epsilon=epsilon
        self.len_molecular_hidden_layers=len_molecular_hidden_layers
        self.molecular_nbrs = molecular_nbrs
        self.conv_net=conv_bool
        self.type_feature=type_bool
        self.save_path = save_path+'/'

    def train_ac(self):
        epoch_loss=[]
        for e in range(self.epochs):
            file_loss=[]
            filelist=[d for d in self.numpylist if 'AE' not in d]
            for f in filelist:
                if self.print_data:
                    if e==0:
                        print (f)

                (X, nbrs, resnums) = helper.get_data_arrays(f)

                #X=np.load(f)
                #X=X[0:20,:,:,:] # please remove it for original test
                #print("X shape: ", X.shape)
                #sys.exit(0)

                # Bond lengths are in the range of 0 - 10 angstroms -- normalize it to 0 - 1
                if self.type_feature:
                    Xnorm=np.concatenate([X[:,:,:,0:3]/255.,X[:,:,:,3:8],X[:,:,:,8:]/10.],axis=3)  ## normalizing the location coordinates and bond lengths and scale type encoding
                else:
                    Xnorm=np.concatenate([X[:,:,:,0:3]/255.,X[:,:,:,8:]/10.],axis=3) ## only consider the location coordinates and bond lengths per molecule

                #print("Xnorm shape: ", Xnorm.shape)
                ### Code for sub-autoencoder for molecule feature learing
                #having some problems

                num_frames=X.shape[0]
                num_molecules=X.shape[1]
                input_feature_dim=np.prod(Xnorm.shape[2:])
                XP=[]


                for i in range(num_frames):
                    #print(i)
                    #print(num_frames)
                    if self.conv_net:
                        xt=Xnorm[i].reshape(X.shape[1],input_feature_dim)
                        xt= helper.append_nbrs(xt, nbrs[i], self.molecular_nbrs)

                        yt=xt.copy()
                        xt = xt.reshape(xt.shape[0],1,xt.shape[1])

                    else:
                        xt=Xnorm[i].reshape(X.shape[1],input_feature_dim)
                        xt= helper.append_nbrs(xt, nbrs[i], self.molecular_nbrs)

                        yt=xt.copy()
                    #print("xt shape: ", xt.shape)
                    w=self.molecular_model.get_weights()
                    #print (self.molecular_model.evaluate(xt,yt,verbose=0)[0])
                    count = 0
                    while self.molecular_model.evaluate(xt,yt,verbose=0)[0]>self.epsilon or count < 1:
                        print ('[Frame %d]' % (i),'Inner AE loss..', self.molecular_model.evaluate(xt,yt,verbose=0)[0])
                        self.molecular_model.set_weights(w)
                        #print(xt.shape)
                        self.molecular_model.fit(xt, yt,epochs=self.mb_epochs,callbacks=self.callbacks,verbose=2)
                        w=self.molecular_model.get_weights()
                        count += 1
                    yp=get_activations(self.molecular_model,self.len_molecular_hidden_layers,xt)
                    XP.append(yp)
                XP=np.array(XP)
                fout=self.save_path + f.split('/')[-1].split('.npz')[0]+'_AE'+'_Include%s'%self.type_feature+'_Conv%s'%self.conv_net+'.npy'
                if e==0:
                    np.save(fout,XP)
                '''
                # Flatten the output of the convolutional layer into a single dimension per frame
                X_train=XP.copy().reshape(XP.shape[0],np.prod(XP.shape[1:]))
                y_train=X_train.copy()
                imggen=self.datagen.flow(X_train, y_train, batch_size=self.batch_size)
                N_iter=XP.shape[0]//self.batch_size

                iter_loss=[]
                for _ in range(N_iter+1):
                    x,y=next(imggen)
                    loss_data=self.model.train_on_batch(x,y)
                    iter_loss.append(loss_data)
                #print (iter_loss)
                file_loss.append(np.array(iter_loss).mean(axis=0))


            print ('Loss on epoch %d:'%e, file_loss[-1])
            epoch_loss.append(np.array(file_loss).mean(axis=0))
            '''
            for e in range(self.epochs):
                (X, nbrs, resnums) = helper.get_data_arrays(f)
                # Bond lengths are in the range of 0 - 10 angstroms -- normalize it to 0 - 1
                if self.type_feature:
                    Xnorm=np.concatenate([X[:,:,:,0:3]/255.,X[:,:,:,3:8],X[:,:,:,8:]/10.],axis=3)
                else:
                    Xnorm=np.concatenate([X[:,:,:,0:3]/255.,X[:,:,:,8:]/10.],axis=3)

                num_frames=X.shape[0]
                num_molecules=X.shape[1]
                input_feature_dim=np.prod(Xnorm.shape[2:])
                XP=[]

                for i in range(num_frames):

                    xt=Xnorm[i].reshape(X.shape[1],input_feature_dim)
                    xt= helper.append_nbrs(xt, nbrs[i], self.molecular_nbrs)
                    if self.conv_net:
                        xt = xt.reshape(xt.shape[0],1,xt.shape[1])
                    w=self.molecular_model.get_weights()
                    yp=get_activations(self.molecular_model,self.len_molecular_hidden_layers,xt)
                    XP.append(yp)
                    fout=self.save_path + f.split('/')[-1].split('.npz')[0]+'_AE'+'_Include%s'%self.type_feature+'_Conv%s'%self.conv_net+'_final.npy'
            np.save(fout,XP)
        return epoch_loss
