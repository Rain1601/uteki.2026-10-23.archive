import Foundation
import AVFoundation
import AppKit

let args = CommandLine.arguments
guard args.count == 3 else { fatalError("Usage: swift encode-film.swift FRAME_DIR OUTPUT.mp4") }
let frames = URL(fileURLWithPath: args[1])
let output = URL(fileURLWithPath: args[2])
if FileManager.default.fileExists(atPath: output.path) { try FileManager.default.removeItem(at: output) }
let writer = try AVAssetWriter(outputURL: output, fileType: .mp4)
let settings: [String: Any] = [AVVideoCodecKey: AVVideoCodecType.h264, AVVideoWidthKey: 960, AVVideoHeightKey: 540,
    AVVideoCompressionPropertiesKey: [AVVideoAverageBitRateKey: 1800000, AVVideoProfileLevelKey: AVVideoProfileLevelH264MainAutoLevel]]
let input = AVAssetWriterInput(mediaType: .video, outputSettings: settings)
input.expectsMediaDataInRealTime = false
let adapter = AVAssetWriterInputPixelBufferAdaptor(assetWriterInput: input, sourcePixelBufferAttributes: [
    kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32ARGB,
    kCVPixelBufferWidthKey as String: 960, kCVPixelBufferHeightKey as String: 540])
writer.add(input)
writer.shouldOptimizeForNetworkUse = true
guard writer.startWriting() else { fatalError("Writer could not start: \(String(describing: writer.error))") }
writer.startSession(atSourceTime: .zero)
for i in 0..<168 {
    while !input.isReadyForMoreMediaData {
        if writer.status == .failed { fatalError("Writer failed: \(String(describing: writer.error))") }
        Thread.sleep(forTimeInterval: 0.005)
    }
    let url = frames.appendingPathComponent(String(format:"%04d.png", i))
    guard let image = NSImage(contentsOf: url), let cg = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else { fatalError("Missing frame \(url.path)") }
    var buffer: CVPixelBuffer?
    CVPixelBufferPoolCreatePixelBuffer(nil, adapter.pixelBufferPool!, &buffer)
    guard let px = buffer else { fatalError("Pixel buffer allocation failed") }
    CVPixelBufferLockBaseAddress(px, [])
    let context = CGContext(data: CVPixelBufferGetBaseAddress(px), width: 960, height: 540, bitsPerComponent: 8,
        bytesPerRow: CVPixelBufferGetBytesPerRow(px), space: CGColorSpaceCreateDeviceRGB(),
        bitmapInfo: CGImageAlphaInfo.noneSkipFirst.rawValue)!
    context.draw(cg, in: CGRect(x: 0, y: 0, width: 960, height: 540))
    CVPixelBufferUnlockBaseAddress(px, [])
    guard adapter.append(px, withPresentationTime: CMTime(value: Int64(i), timescale: 24)) else { fatalError("Append failed: \(String(describing: writer.error))") }
}
input.markAsFinished()
let done = DispatchSemaphore(value: 0)
writer.finishWriting { done.signal() }
done.wait()
guard writer.status == .completed else { fatalError("Encoding failed: \(String(describing: writer.error))") }
let asset = AVURLAsset(url: output)
let tracks = asset.tracks(withMediaType: .video)
guard let track = tracks.first else { fatalError("No video track") }
let reader = try AVAssetReader(asset: asset)
let readerOutput = AVAssetReaderTrackOutput(track: track, outputSettings: [kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA])
reader.add(readerOutput)
guard reader.startReading() else { fatalError("Could not start decoder") }
var decoded = 0
while readerOutput.copyNextSampleBuffer() != nil { decoded += 1 }
guard reader.status == .completed, decoded == 168 else { fatalError("Decoded \(decoded) frames, status \(reader.status)") }
print("H.264 MP4: \(track.naturalSize.width)x\(track.naturalSize.height), duration \(CMTimeGetSeconds(asset.duration)) s, \(decoded) decoded frames, \(asset.tracks(withMediaType: .audio).count) audio tracks")
