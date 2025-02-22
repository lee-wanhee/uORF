import os

import torchvision.transforms.functional as TF

from data.base_dataset import BaseDataset
from PIL import Image
import torch
import glob
import numpy as np
import random
# new repository

class MultiscenesDataset(BaseDataset):
    @staticmethod
    def modify_commandline_options(parser, is_train):
        parser.set_defaults(input_nc=3, output_nc=3)
        parser.add_argument('--n_scenes', type=int, default=1000, help='dataset length is #scenes')
        parser.add_argument('--n_img_each_scene', type=int, default=10, help='for each scene, how many images to load in a batch')
        parser.add_argument('--no_shuffle', action='store_true')
        parser.add_argument('--mask_size', type=int, default=128)
        return parser

    def __init__(self, opt):
        """Initialize this dataset class.

        Parameters:
            opt (Option class) -- stores all the experiment flags; needs to be a subclass of BaseOptions
        """
        BaseDataset.__init__(self, opt)
        self.n_scenes = opt.n_scenes
        self.n_img_each_scene = opt.n_img_each_scene
        image_filenames = sorted(glob.glob(os.path.join(opt.dataroot, '*.png')))  # root/00000_sc000_az00_el00.png
        mask_filenames = sorted(glob.glob(os.path.join(opt.dataroot, '*_mask.png')))
        fg_mask_filenames = sorted(glob.glob(os.path.join(opt.dataroot, '*_mask_for_moving.png')))
        moved_filenames = sorted(glob.glob(os.path.join(opt.dataroot, '*_moved.png')))
        bg_mask_filenames = sorted(glob.glob(os.path.join(opt.dataroot, '*_mask_for_bg.png')))
        bg_in_mask_filenames = sorted(glob.glob(os.path.join(opt.dataroot, '*_mask_for_providing_bg.png')))
        changed_filenames = sorted(glob.glob(os.path.join(opt.dataroot, '*_changed.png')))
        bg_in_filenames = sorted(glob.glob(os.path.join(opt.dataroot, '*_providing_bg.png')))
        changed_filenames_set, bg_in_filenames_set = set(changed_filenames), set(bg_in_filenames)
        bg_mask_filenames_set, bg_in_mask_filenames_set = set(bg_mask_filenames), set(bg_in_mask_filenames)
        image_filenames_set, mask_filenames_set = set(image_filenames), set(mask_filenames)
        fg_mask_filenames_set, moved_filenames_set = set(fg_mask_filenames), set(moved_filenames)
        filenames_set = image_filenames_set - mask_filenames_set - fg_mask_filenames_set - moved_filenames_set - changed_filenames_set - bg_in_filenames_set - bg_mask_filenames_set - bg_in_mask_filenames_set
        filenames = sorted(list(filenames_set))
        self.scenes = []
        for i in range(self.n_scenes):
            scene_filenames = [x for x in filenames if 'sc{:04d}_frame5'.format(i) in x]
            self.scenes.append(scene_filenames)

    def _transform(self, img):
        img = TF.resize(img, (self.opt.load_size, self.opt.load_size))
        img = TF.to_tensor(img)
        img = TF.normalize(img, [0.5] * img.shape[0], [0.5] * img.shape[0])  # [0,1] -> [-1,1]
        return img

    def _transform_mask(self, img):
        img = TF.resize(img, (self.opt.mask_size, self.opt.mask_size), Image.NEAREST)
        img = TF.to_tensor(img)
        img = TF.normalize(img, [0.5] * img.shape[0], [0.5] * img.shape[0])  # [0,1] -> [-1,1]
        return img

    def __getitem__(self, index):
        """Return a data point and its metadata information.

        Parameters:
            index - - a random integer for data indexing, here it is scene_idx
        """
        scene_idx = index
        scene_filenames = self.scenes[scene_idx]
        if self.opt.isTrain and not self.opt.no_shuffle:
            filenames = random.sample(scene_filenames, self.n_img_each_scene)
        else:
            filenames = scene_filenames[:self.n_img_each_scene]
        rets = []
        for path in filenames:
            img = Image.open(path).convert('RGB')
            img_data = self._transform(img)
            pose_path = path.replace('.png', '_RT.txt')
            try:
                pose = np.loadtxt(pose_path)
            except FileNotFoundError:
                print('filenotfound error: {}'.format(pose_path))
                assert False
            pose = torch.tensor(pose, dtype=torch.float32)
            azi_path = pose_path.replace('_RT.txt', '_azi_rot.txt')
            if self.opt.fixed_locality:
                azi_rot = np.eye(3)  # not used; placeholder
            else:
                azi_rot = np.loadtxt(azi_path)
            azi_rot = torch.tensor(azi_rot, dtype=torch.float32)
            depth_path = path.replace('.png', '_depth.npy')
            if os.path.isfile(depth_path):
                depth = np.load(depth_path)  # HxWx1
                depth = torch.from_numpy(depth)  # HxWx1
                depth = depth.permute([2, 0, 1])  # 1xHxW
                ret = {'img_data': img_data, 'path': path, 'cam2world': pose, 'azi_rot': azi_rot, 'depth': depth}
            else:
                ret = {'img_data': img_data, 'path': path, 'cam2world': pose, 'azi_rot': azi_rot}
            mask_path = path.replace('.png', '_mask.png')
            if os.path.isfile(mask_path):
                mask = Image.open(mask_path).convert('RGB')
                mask_l = mask.convert('L')
                mask = self._transform_mask(mask)
                ret['mask'] = mask
                mask_l = self._transform_mask(mask_l)
                mask_flat = mask_l.flatten(start_dim=0)  # HW,
                greyscale_dict = mask_flat.unique(sorted=True)  # 8,
                onehot_labels = mask_flat[:, None] == greyscale_dict  # HWx8, one-hot
                onehot_labels = onehot_labels.type(torch.uint8)
                mask_idx = onehot_labels.argmax(dim=1)  # HW
                bg_color = greyscale_dict[1]
                fg_idx = mask_flat != bg_color  # HW
                ret['mask_idx'] = mask_idx
                ret['fg_idx'] = fg_idx
                obj_idxs = []
                for i in range(len(greyscale_dict)):
                    obj_idx = mask_l == greyscale_dict[i]  # 1xHxW
                    obj_idxs.append(obj_idx)
                obj_idxs = torch.stack(obj_idxs)  # Kx1xHxW
                ret['obj_idxs'] = obj_idxs  # KxHxW
            rets.append(ret)
        return rets

    def __len__(self):
        """Return the total number of images in the dataset."""
        return self.n_scenes


def collate_fn(batch):
    # "batch" is a list (len=batch_size) of list (len=n_img_each_scene) of dict
    flat_batch = [item for sublist in batch for item in sublist]
    img_data = torch.stack([x['img_data'] for x in flat_batch])
    paths = [x['path'] for x in flat_batch]
    cam2world = torch.stack([x['cam2world'] for x in flat_batch])
    azi_rot = torch.stack([x['azi_rot'] for x in flat_batch])
    if 'depth' in flat_batch[0]:
        depths = torch.stack([x['depth'] for x in flat_batch])  # Bx1xHxW
    else:
        depths = None
    ret = {
        'img_data': img_data,
        'paths': paths,
        'cam2world': cam2world,
        'azi_rot': azi_rot,
        'depths': depths
    }
    if 'mask' in flat_batch[0]:
        masks = torch.stack([x['mask'] for x in flat_batch])
        ret['masks'] = masks
        mask_idx = torch.stack([x['mask_idx'] for x in flat_batch])
        ret['mask_idx'] = mask_idx
        fg_idx = torch.stack([x['fg_idx'] for x in flat_batch])
        ret['fg_idx'] = fg_idx
        obj_idxs = flat_batch[0]['obj_idxs']  # Kx1xHxW
        ret['obj_idxs'] = obj_idxs
    return ret
