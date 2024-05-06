import os
import gc
import re
import time

from singleVis.utils import *
from singleVis.eval.evaluate import evaluate_inv_accu

"""
DataContainder module
1. prepare data
2. estimate boundary
3. provide data
"""

class DataProvider:
    def __init__(self, content_path, model, epoch_start, epoch_end, epoch_period, split, device, verbose=1):
        self.content_path = content_path
        self.model = model
        self.s = epoch_start
        self.e = epoch_end
        self.p = epoch_period
        self.split = split
        self.DEVICE = device
        self.verbose = verbose
        self.model_path = os.path.join(self.content_path, "Model")
        if verbose:
            print("Finish initialization...")

    @property
    def train_num(self):
        training_data_path = os.path.join(self.content_path, "Training_data")
        training_data = torch.load(os.path.join(training_data_path, "training_dataset_data.pth"),
                                   map_location=self.DEVICE)
        train_num = len(training_data)
        del training_data
        gc.collect()
        return train_num

    @property
    def test_num(self):
        testing_data_path = os.path.join(self.content_path, "Testing_data")
        testing_data = torch.load(os.path.join(testing_data_path, "testing_dataset_data.pth"),
                                  map_location=self.DEVICE)
        test_num = len(testing_data)
        del testing_data
        gc.collect()
        return test_num
    
    @property
    def representation_dim(self):
        train_data_loc = os.path.join(self.model_path, "Epoch_{:d}".format(self.s), "train_data.npy")
        try:
            train_data = np.load(train_data_loc)
            repr_dim = np.prod(train_data.shape[1:])
            return repr_dim
        except Exception as e:
            return None


    def _meta_data(self):
        time_inference = list()
        training_data_path = os.path.join(self.content_path, "Training_data")
        training_data = torch.load(os.path.join(training_data_path, "training_dataset_data.pth"),
                                        map_location=self.DEVICE)
        testing_data_path = os.path.join(self.content_path, "Testing_data")
        testing_data = torch.load(os.path.join(testing_data_path, "testing_dataset_data.pth"),
                                       map_location=self.DEVICE)

        for n_epoch in range(self.s, self.e + 1, self.p):
            t_s = time.time()

            # make it possible to choose a subset of testing data for testing
            test_index_file = os.path.join(self.model_path, "Epoch_{:d}".format(n_epoch), "test_index.json")
            if os.path.exists(test_index_file):
                test_index = load_labelled_data_index(test_index_file)
            else:
                test_index = range(len(testing_data))
            testing_data = testing_data[test_index]

            # model_location = os.path.join(self.model_path, "Epoch_{:d}".format(n_epoch), "subject_model.pth")
            # self.model.load_state_dict(torch.load(model_location, map_location=torch.device("cpu")))
            # self.model = self.model.to(self.DEVICE)
            # self.model.eval()
            # repr_model = torch.nn.Sequential(*(list(self.model.children())[:self.split]))
            repr_model = self.feature_function(n_epoch)
            

            # training data clustering
            data_pool_representation = batch_run(repr_model, training_data)
            location = os.path.join(self.model_path, "Epoch_{:d}".format(n_epoch), "train_data.npy")
            np.save(location, data_pool_representation)

            # test data
            test_data_representation = batch_run(repr_model, testing_data)
            location = os.path.join(self.model_path, "Epoch_{:d}".format(n_epoch), "test_data.npy")
            np.save(location, test_data_representation)

            t_e = time.time()
            time_inference.append(t_e-t_s)
            if self.verbose > 0:
                print("Finish inferencing data for Epoch {:d}...".format(n_epoch))
        print(
            "Average time for inferencing data: {:.4f}".format(sum(time_inference) / len(time_inference)))

        # save result
        save_dir = os.path.join(self.model_path, "SV_time.json")
        if not os.path.exists(save_dir):
            evaluation = dict()
        else:
            f = open(save_dir, "r")
            evaluation = json.load(f)
            f.close()
        evaluation["data_inference"] = round(sum(time_inference) / len(time_inference), 3)
        with open(save_dir, 'w') as f:
            json.dump(evaluation, f)

        del training_data
        del testing_data
        gc.collect()

    def _estimate_boundary(self, num, l_bound):
        '''
        Preprocessing data. This process includes find_border_points and find_border_centers
        save data for later training
        '''

        time_borders_gen = list()
        training_data_path = os.path.join(self.content_path, "Training_data")
        training_data = torch.load(os.path.join(training_data_path, "training_dataset_data.pth"),
                                   map_location=self.DEVICE)
        for n_epoch in range(self.s, self.e + 1, self.p):
            index_file = os.path.join(self.model_path, "Epoch_{:d}".format(n_epoch), "index.json")
            index = load_labelled_data_index(index_file)
            training_data = training_data[index]

            model_location = os.path.join(self.model_path, "Epoch_{:d}".format(n_epoch), "subject_model.pth")
            self.model.load_state_dict(torch.load(model_location, map_location=torch.device("cpu")))
            self.model = self.model.to(self.DEVICE)
            self.model.eval()

            repr_model = torch.nn.Sequential(*(list(self.model.children())[:self.split]))

            t0 = time.time()
            confs = batch_run(self.model, training_data)
            preds = np.argmax(confs, axis=1).squeeze()
            # TODO how to choose the number of boundary points?
            num_adv_eg = num
            border_points, _, _ = get_border_points(model=self.model, input_x=training_data, confs=confs, predictions=preds, device=self.DEVICE, l_bound=l_bound, num_adv_eg=num_adv_eg, lambd=0.05, verbose=0)
            t1 = time.time()
            time_borders_gen.append(round(t1 - t0, 4))

            # get gap layer data
            border_points = border_points.to(self.DEVICE)
            border_centers = batch_run(repr_model, border_points)
            location = os.path.join(self.model_path, "Epoch_{:d}".format(n_epoch), "border_centers.npy")
            np.save(location, border_centers)

            location = os.path.join(self.model_path, "Epoch_{:d}".format(n_epoch), "ori_border_centers.npy")
            np.save(location, border_points.cpu().numpy())

            num_adv_eg = num
            border_points, _, _ = get_border_points(model=self.model, input_x=training_data, confs=confs, predictions=preds, device=self.DEVICE, l_bound=l_bound, num_adv_eg=num_adv_eg, lambd=0.05, verbose=0)

            # get gap layer data
            border_points = border_points.to(self.DEVICE)
            border_centers = batch_run(repr_model, border_points)
            location = os.path.join(self.model_path, "Epoch_{:d}".format(n_epoch), "test_border_centers.npy")
            np.save(location, border_centers)

            location = os.path.join(self.model_path, "Epoch_{:d}".format(n_epoch), "test_ori_border_centers.npy")
            np.save(location, border_points.cpu().numpy())

            if self.verbose > 0:
                print("Finish generating borders for Epoch {:d}...".format(n_epoch))
        print(
            "Average time for generate border points: {:.4f}".format(sum(time_borders_gen) / len(time_borders_gen)))

        # save result
        save_dir = os.path.join(self.model_path, "SV_time.json")
        if not os.path.exists(save_dir):
            evaluation = dict()
        else:
            f = open(save_dir, "r")
            evaluation = json.load(f)
            f.close()
        evaluation["data_B_gene"] = round(sum(time_borders_gen) / len(time_borders_gen), 3)
        with open(save_dir, 'w') as f:
            json.dump(evaluation, f)

    def initialize(self, num, l_bound):
        self._meta_data()
        self._estimate_boundary(num, l_bound)

    def train_representation(self, epoch):
        # load train data
        train_data_loc = os.path.join(self.model_path, "Epoch_{:d}".format(epoch), "train_data.npy")
        index_file = os.path.join(self.model_path, "Epoch_{:d}".format(epoch), "index.json")
        index = load_labelled_data_index(index_file)
        try:
            train_data = np.load(train_data_loc)
            train_data = train_data[index]
        except Exception as e:
            print("no train data saved for Epoch {}".format(epoch))
            train_data = None
        return train_data.squeeze()
    
    def train_labels(self, epoch):
        # load train data
        training_data_loc = os.path.join(self.content_path, "Training_data", "training_dataset_label.pth")
        index_file = os.path.join(self.model_path, "Epoch_{:d}".format(epoch), "index.json")
        index = load_labelled_data_index(index_file)
        try:
            training_labels = torch.load(training_data_loc, map_location=self.DEVICE)
            training_labels = training_labels[index]
        except Exception as e:
            print("no train labels saved for Epoch {}".format(epoch))
            training_labels = None
        return training_labels.cpu().numpy()

    def test_representation(self, epoch):
        data_loc = os.path.join(self.model_path, "Epoch_{:d}".format(epoch), "test_data.npy")
        try:
            test_data = np.load(data_loc).squeeze()
            index_file = os.path.join(self.model_path, "Epoch_{:d}".format(epoch), "test_index.json")
            if os.path.exists(index_file):
                index = load_labelled_data_index(index_file)
                test_data = test_data[index]
        except Exception as e:
            print("no test data saved for Epoch {}".format(epoch))
            test_data = None
        # max_x = self.max_norm(epoch)
        return test_data
    
    def test_labels(self, epoch):
        # load train data
        testing_data_loc = os.path.join(self.content_path, "Testing_data", "testing_dataset_label.pth")
        try:
            testing_labels = torch.load(testing_data_loc).to(device=self.DEVICE)
            index_file = os.path.join(self.model_path, "Epoch_{:d}".format(epoch), "test_index.json")
            if os.path.exists(index_file):
                idxs = load_labelled_data_index(index_file)
                testing_labels = testing_labels[idxs]
        except Exception as e:
            print("no train labels saved for Epoch {}".format(epoch))
            testing_labels = None
        return testing_labels.cpu().numpy()

    def border_representation(self, epoch):
        border_centers_loc = os.path.join(self.model_path, "Epoch_{:d}".format(epoch),
                                          "border_centers.npy")
        try:
            border_centers = np.load(border_centers_loc).squeeze()
        except Exception as e:
            print("no border points saved for Epoch {}".format(epoch))
            border_centers = None
        return border_centers
    
    def test_border_representation(self, epoch):
        border_centers_loc = os.path.join(self.model_path, "Epoch_{:d}".format(epoch),
                                          "test_border_centers.npy")
        try:
            border_centers = np.load(border_centers_loc).squeeze()
        except Exception as e:
            print("no border points saved for Epoch {}".format(epoch))
            border_centers = None
        return border_centers
    
    def max_norm(self, epoch):
        train_data_loc = os.path.join(self.model_path, "Epoch_{:d}".format(epoch), "train_data.npy")
        index_file = os.path.join(self.model_path, "Epoch_{:d}".format(epoch), "index.json")
        index = load_labelled_data_index(index_file)
        try:
            train_data = np.load(train_data_loc)
            train_data = train_data[index]
            max_x = np.linalg.norm(train_data, axis=1).max()
        except Exception as e:
            print("no train data saved for Epoch {}".format(epoch))
            max_x = None
        return max_x


    def prediction_function(self, epoch):
        model_location = os.path.join(self.model_path, "Epoch_{:d}".format(epoch), "subject_model.pth")
        self.model.load_state_dict(torch.load(model_location, map_location=torch.device("cpu")))
        self.model = self.model.to(self.DEVICE)
        self.model.eval()

        pred_fn = self.model.prediction
        return pred_fn

    def feature_function(self, epoch):
        model_location = os.path.join(self.model_path, "Epoch_{:d}".format(epoch), "subject_model.pth")
        self.model.load_state_dict(torch.load(model_location, map_location=torch.device("cpu")))
        self.model = self.model.to(self.DEVICE)
        self.model.eval()

        fea_fn = self.model.feature
        return fea_fn

    def get_pred(self, epoch, data):
        '''
        get the prediction score for data in epoch_id
        :param data: numpy.ndarray
        :param epoch_id:
        :return: pred, numpy.ndarray
        '''
        prediction_func = self.prediction_function(epoch)

        data = torch.from_numpy(data)
        data = data.to(self.DEVICE)
        pred = batch_run(prediction_func, data)
        return pred.squeeze()

    def training_accu(self, epoch):
        data = self.train_representation(epoch)
        labels = self.train_labels(epoch)
        pred = self.get_pred(epoch, data).argmax(-1)
        val = evaluate_inv_accu(labels, pred)
        return val

    def testing_accu(self, epoch):
        data = self.test_representation(epoch)
        labels = self.test_labels()
        test_index_file = os.path.join(self.model_path, "Epoch_{}".format(epoch), "test_index.json")
        if os.path.exists(test_index_file):
            index = load_labelled_data_index(test_index_file)
            labels = labels[index]
        pred = self.get_pred(epoch, data).argmax(-1)
        val = evaluate_inv_accu(labels, pred)
        return val
    
    def is_deltaB(self, epoch, data):
        """
        check wheter input vectors are lying on delta-boundary or not
        :param epoch_id:
        :param data: numpy.ndarray
        :return: numpy.ndarray, boolean, True stands for is_delta_boundary
        """
        preds = self.get_pred(epoch, data)
        border = is_B(preds)
        return border
