# Kiera's ShapeKey Sync

A powerful Blender addon that makes it easy to sync shapekeys between multiple objects. Perfect for character rigging, facial animation, and any workflow that requires synchronized shapekeys across multiple meshes.

![Blender Version](https://img.shields.io/badge/Blender-4.3.1_--_5.2_LTS-blue)
![License](https://img.shields.io/badge/License-GPL--3.0--or--later-blue)

## ✨ Features

- 🔄 **Easy Sync**: Sync shapekeys between multiple objects with a single click
- 👁️ **Live Preview**: Test shapekey values in real-time before committing
- 📊 **Smart Tracking**: Keep track of all your synced shapekeys in one place
- 🎯 **Batch Operations**: Sync or unsync multiple shapekeys at once
- 🎨 **User-Friendly**: Clean interface in the 3D View sidebar

## 🚀 Quick Start

### Installation

1. Download the latest release from the [Releases](https://github.com/mkiera/shapekey-sync/releases) page
2. Open Blender
3. Go to `Edit > Preferences > Add-ons`
4. Click "Install" and select the downloaded `.zip` file
5. Enable the addon by checking the box next to "Animation: Kiera's ShapeKey Sync"

### Basic Usage

1. Open the 3D View
2. Press `N` to open the sidebar if it's not visible
3. Look for the "ShapeKey Sync" tab
4. Set up your sync:
   - Select your source object (the "driver")
   - Add target objects (the "followers")
   - Click "Refresh List" to see available shapekeys
   - Select which shapekeys to sync
   - Click "Sync ShapeKeys" to create the connections

## 🎮 Detailed Usage

### Preview Mode

The preview mode lets you test shapekey values before committing to them:

1. Select a shapekey from the dropdown menu
2. Use the slider to adjust the value
3. See the changes in real-time on both source and target objects
4. Perfect for testing and fine-tuning your shapekeys

### Managing Synced Keys

Keep track of your synced shapekeys with these features:

- **View All Syncs**: See all active syncs in the "Synced Keys" section
- **Remove Individual Syncs**: Click the X button next to any key or object
- **Batch Remove**: Use "Unsync All" to remove all syncs at once
- **Organize by Object**: Keys are grouped by object for easy management

## 💻 Requirements

- Blender 4.3.1 or newer, including the 5.x series (5.0, 5.1, and 5.2 LTS)
- Objects must have shapekeys to sync

## 🤝 Contributing

Found a bug or have a feature request? Feel free to:
- Open an issue
- Submit a pull request
- Contact me directly

## 📄 License

This addon is released under the GNU General Public License v3.0 or later. See the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

Thanks to the Blender community for their support and feedback! 