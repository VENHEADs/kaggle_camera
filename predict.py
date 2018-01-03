import argparse
from torchvision import transforms
import utils
import data_loader
from tqdm import tqdm
import models
import torch
from torch.utils.data import DataLoader
import numpy as np
from torch import nn
from pathlib import Path
import torch.nn.functional as F
import pandas as pd
from scipy.stats.mstats import gmean


img_transform = transforms.Compose([
    transforms.RandomCrop(512),
    transforms.ToTensor(),
    transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
])


class PredictionDataset:
    def __init__(self, paths):
        self.paths = paths

    def __len__(self):
        return len(self.paths)

    def __getitem__(self, idx):
        path = self.paths[idx]
        image = utils.load_image(path)
        return utils.img_transform(image), path.stem


def predict(model, from_paths, batch_size: int, to_path=None):
    loader = DataLoader(
        dataset=PredictionDataset(from_paths),
        shuffle=False,
        batch_size=batch_size,
        num_workers=args.workers,
        pin_memory=True
    )

    result = []

    for batch_num, (inputs, stems) in enumerate(tqdm(loader, desc='Predict')):
        inputs = utils.variable(inputs, volatile=True)
        outputs = F.softmax(model(inputs))
        result += [outputs.data.cpu().numpy()]

    return np.vstack(result)


def get_model(fold):
    num_classes = data_loader.num_classes

    model = models.ResNetFinetune(num_classes, net_cls=models.M.resnet50)
    model = utils.cuda(model)

    if utils.cuda_is_available:
        model = nn.DataParallel(model, device_ids=[0]).cuda()

    state = torch.load(
        str(Path(args.root) / 'best-model_{fold}.pt'.format(fold=fold)))

    model.load_state_dict(state['model'])
    model.eval()

    return model


def add_args(parser):
    arg = parser.add_argument
    arg('--root', default='data/models/resnet50_50', help='model path')
    arg('--batch-size', type=int, default=20)
    arg('--lr', type=float, default=0.0001)
    arg('--workers', type=int, default=12)


if __name__ == '__main__':
    random_state = 2016

    parser = argparse.ArgumentParser()

    arg = parser.add_argument
    add_args(parser)
    args = parser.parse_args()

    data_path = Path('data')

    num_folds = 5
    test_images = sorted(list((data_path / 'test').glob('*.tif')))

    result = []

    for fold in range(num_folds):
        model = get_model(fold)
        preds = predict(model, test_images, args.batch_size)

        result += [preds]

    # pred_probs = np.dstack(result).mean(axis=2)
    pred_probs = gmean(np.dstack(result), axis=2)

    max_ind = np.argmax(pred_probs, axis=1)

    train_df = pd.read_csv(str(data_path / 'train_crops_df.csv'))
    class_map = dict(zip(train_df['class_ind'].values, train_df['class'].values))

    preds = [class_map[x] for x in max_ind]

    df = pd.DataFrame({'fname': [x.name for x in test_images], 'camera': preds})
    df.to_csv(str(data_path / '2.csv'), index=False)
