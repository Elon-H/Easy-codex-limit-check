// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "quota-menu-bar",
    platforms: [
        .macOS(.v13),
    ],
    products: [
        .executable(name: "QuotaMenuBar", targets: ["QuotaMenuBar"]),
    ],
    targets: [
        .executableTarget(
            name: "QuotaMenuBar",
            path: "Sources",
        ),
    ]
)
