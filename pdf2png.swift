import Foundation
import CoreGraphics
import ImageIO

let args = CommandLine.arguments
guard args.count >= 4 else {
    print("Usage: pdf2png <input.pdf> <output_dir> <dpi> [pages]")
    print("  pages: comma-separated page numbers (1-based), e.g. \"1,3,5\"")
    exit(1)
}

let pdfPath = args[1]
let outputDir = args[2]
let dpi = Double(args[3]) ?? 150.0
let scale = dpi / 72.0

// Parse optional page range
var requestedPages: Set<Int>? = nil
if args.count >= 5 {
    requestedPages = Set(args[4].split(separator: ",").compactMap { Int($0) })
}

guard let pdfURL = CFURLCreateWithFileSystemPath(nil, pdfPath as CFString, .cfurlposixPathStyle, false),
      let pdfDoc = CGPDFDocument(pdfURL) else {
    print("Error: Cannot open PDF")
    exit(1)
}

let fm = FileManager.default
try? fm.createDirectory(atPath: outputDir, withIntermediateDirectories: true)

let pageCount = pdfDoc.numberOfPages
var rendered = 0
for i in 1...pageCount {
    // Skip pages not in requested set
    if let requested = requestedPages, !requested.contains(i) {
        continue
    }

    guard let page = pdfDoc.page(at: i) else { continue }
    let rect = page.getBoxRect(.mediaBox)
    let w = Int(rect.width * scale)
    let h = Int(rect.height * scale)

    let cs = CGColorSpaceCreateDeviceRGB()
    guard let ctx = CGContext(data: nil, width: w, height: h, bitsPerComponent: 8,
                              bytesPerRow: w * 4, space: cs,
                              bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { continue }
    ctx.setFillColor(red: 1, green: 1, blue: 1, alpha: 1)
    ctx.fill(CGRect(x: 0, y: 0, width: w, height: h))
    ctx.scaleBy(x: scale, y: scale)
    ctx.drawPDFPage(page)

    guard let image = ctx.makeImage() else { continue }
    let filename = String(format: "page_%03d.png", i)
    let outURL = URL(fileURLWithPath: outputDir).appendingPathComponent(filename)
    guard let dest = CGImageDestinationCreateWithURL(outURL as CFURL, "public.png" as CFString, 1, nil) else { continue }
    CGImageDestinationAddImage(dest, image, nil)
    CGImageDestinationFinalize(dest)
    rendered += 1
}
print("Rendered \(rendered)/\(pageCount) pages to \(outputDir)")
