import torch
import albumentations as A
from albumentations.pytorch import ToTensorV2
from torch.utils.data import DataLoader
from tqdm import tqdm
import torch.nn as nn
import torch.optim as optim


# local imports
from model import StockwishEvalMLP
from dataset import ChessDataset
from utils import calculate_validation_loss_epoch

# Hyper parameters
LEARNING_RATE = 1e-3
MOMENTUM = 0.7
NESTEROV = True
BATCH_SIZE = 256
DEVICE = 'cuda' if torch.cuda.is_available() else 'cpu'
NUM_WORKERS = 2
NUM_EPOCHS = 40
PIN_MEMORY = True
LOAD_MODEL = False
ROOT_DIR = "data.csv"
MODEL_PATH = "drive/MyDrive/model_chess.pth"

# Model specific params
NUM_FEATURES = 8 * 8 * 12  # bitmap representation of chessboard is 8 x 8 x num_pieces = 8x8x12
NUM_HIDDEN = 2048  # from paper

# Globals
epoch_num = 0
losses = []

def get_loaders(
        root_dir,
        batch_size,
        train_transform,
        target_transform,
        num_workers=4,
        pin_memory=True,
):

    train_ds = ChessDataset(root_path=root_dir, transform=train_transform, target_transform=target_transform)

    train_loader = DataLoader(
        train_ds,
        batch_size=batch_size,
        num_workers=num_workers,
        pin_memory=pin_memory,
        shuffle=True,
    )

    val_ds = ChessDataset(root_path=root_dir, transform=train_transform, target_transform=target_transform)

    val_loader = DataLoader(
        val_ds,
        batch_size=batch_size,
        num_workers=num_workers,
        pin_memory=pin_memory,
        shuffle=False,
    )

    return train_loader, val_loader


""" 
Does one epoch of training.
"""

def train(train_loader, val_loader, model, optimizer, loss_fn, scaler):
    global epoch_num
    global losses

    loop = tqdm(train_loader)

    for batch_idx, (data, targets) in enumerate(loop):
        batch_losses = []
        data = data.to(device=DEVICE)
        targets = targets.float().unsqueeze(1).to(device=DEVICE)

        # forward
        with torch.cuda.amp.autocast():
            predictions = model(data)
            loss = loss_fn(predictions, targets)
            batch_losses.append(loss)

        # backward
        optimizer.zero_grad()
        scaler.scale(loss).backward()
        scaler.step(optimizer)
        scaler.update()

        loop.set_postfix(loss=loss.item())

    # once epoch is finished, we save state
    epoch_num += 1
    avg_epoch_loss =sum(batch_losses)/len(batch_losses)
    losses.append(avg_epoch_loss)
    torch.save({
        'model_state_dict': model.state_dict(),
        'optim_state_dict': optimizer.state_dict(),
        'epoch': epoch_num,
        'loss_values': losses,
    }, MODEL_PATH)

    # we should keep track of our validation losses as well
    #loss = calculate_validation_loss_epoch(model, DEVICE, val_loader)
    print(f"Epoch {epoch_num} completed. Avg. training loss: {avg_epoch_loss}. Model successfully saved!")


def main():
    global epoch_num
    global losses
    train_transform = lambda x: (torch.tensor(x)).float()
    # if we want to convert evals from centipawns to pure evaluation
    target_transform = None
    #target_transform = None
    model = StockwishEvalMLP(num_features=NUM_FEATURES, num_units_hidden=NUM_HIDDEN, num_classes=1).to(DEVICE)
    loss_fn = nn.MSELoss()  # the paper doesn't explicitly say which loss fn, assuming its a simple MSE loss
    # in paper there is an epsilon parameter of 1e-8, but I am not sure if torch SGD has this parameter
    optimizer = optim.SGD(params=model.parameters(), lr=LEARNING_RATE, momentum=MOMENTUM, nesterov=NESTEROV)
    train_loader, val_loader = get_loaders(ROOT_DIR, BATCH_SIZE, train_transform, target_transform, NUM_WORKERS,
                                           PIN_MEMORY)

    if LOAD_MODEL:
        # Loading a previous stored model from MODEL_PATH variable
        checkpoint = torch.load(MODEL_PATH)
        model.load_state_dict(checkpoint['model_state_dict'])
        optimizer.load_state_dict(checkpoint['optim_state_dict'])
        epoch_num = checkpoint['epoch']
        losses = checkpoint['loss_values']
        print("Model successfully loaded!")

    scaler = torch.cuda.amp.GradScaler()
    for epoch in range(NUM_EPOCHS - epoch_num):
        train(train_loader, val_loader, model, optimizer, loss_fn, scaler)


if __name__ == '__main__':
    main()