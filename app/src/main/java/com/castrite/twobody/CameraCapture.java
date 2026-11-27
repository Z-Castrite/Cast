package com.castrite.twobody;

import android.Manifest;
import android.content.Context;
import android.content.pm.PackageManager;
import android.graphics.ImageFormat;
import android.hardware.camera2.CameraCaptureSession;
import android.hardware.camera2.CameraCharacteristics;
import android.hardware.camera2.CameraDevice;
import android.hardware.camera2.CameraManager;
import android.hardware.camera2.CaptureRequest;
import android.media.Image;
import android.media.ImageReader;
import android.os.Handler;
import android.os.HandlerThread;
import android.util.Size;

import java.nio.ByteBuffer;
import java.util.Collections;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

/**
 * 极简拍照器：Camera2 抓一张 JPEG，同步返回字节。
 *
 * 不给预览、不常驻——拍完就关。它想看一眼的时候才开，省电，也少一个
 * 后台一直亮着的摄像头。
 */
public class CameraCapture {

    private final Context ctx;

    public CameraCapture(Context ctx) {
        this.ctx = ctx;
    }

    public boolean hasPermission() {
        return ctx.checkSelfPermission(Manifest.permission.CAMERA)
                == PackageManager.PERMISSION_GRANTED;
    }

    /** 拍一张，返回 JPEG 字节；失败返回 null。会阻塞到拍完或超时。 */
    public byte[] takePhoto() {
        if (!hasPermission()) {
            return null;
        }
        final AtomicReference<byte[]> out = new AtomicReference<>();
        final CountDownLatch done = new CountDownLatch(1);

        HandlerThread thread = new HandlerThread("twobody-cam");
        thread.start();
        final Handler handler = new Handler(thread.getLooper());

        CameraManager mgr = (CameraManager) ctx.getSystemService(Context.CAMERA_SERVICE);
        CameraDevice[] devRef = new CameraDevice[1];

        try {
            String id = pickCamera(mgr);
            if (id == null) {
                return null;
            }

            Size size = pickSize(mgr, id);
            final ImageReader reader = ImageReader.newInstance(
                    size.getWidth(), size.getHeight(), ImageFormat.JPEG, 1);
            reader.setOnImageAvailableListener(r -> {
                try (Image img = r.acquireLatestImage()) {
                    if (img != null) {
                        ByteBuffer buf = img.getPlanes()[0].getBuffer();
                        byte[] data = new byte[buf.remaining()];
                        buf.get(data);
                        out.set(data);
                    }
                } catch (Exception ignored) {
                } finally {
                    reader.close();
                    done.countDown();
                }
            }, handler);

            mgr.openCamera(id, new CameraDevice.StateCallback() {
                @Override
                public void onOpened(CameraDevice camera) {
                    devRef[0] = camera;
                    try {
                        camera.createCaptureSession(
                                Collections.singletonList(reader.getSurface()),
                                new CameraCaptureSession.StateCallback() {
                                    @Override
                                    public void onConfigured(CameraCaptureSession session) {
                                        try {
                                            CaptureRequest.Builder b = camera.createCaptureRequest(
                                                    CameraDevice.TEMPLATE_STILL_CAPTURE);
                                            b.addTarget(reader.getSurface());
                                            session.capture(b.build(), null, handler);
                                        } catch (Exception e) {
                                            done.countDown();
                                        }
                                    }

                                    @Override
                                    public void onConfigureFailed(CameraCaptureSession session) {
                                        done.countDown();
                                    }
                                }, handler);
                    } catch (Exception e) {
                        done.countDown();
                    }
                }

                @Override
                public void onDisconnected(CameraDevice camera) {
                    camera.close();
                }

                @Override
                public void onError(CameraDevice camera, int error) {
                    camera.close();
                    done.countDown();
                }
            }, handler);

            done.await(12, TimeUnit.SECONDS);
        } catch (Exception ignored) {
        } finally {
            if (devRef[0] != null) {
                try {
                    devRef[0].close();
                } catch (Exception ignored) {
                }
            }
            thread.quitSafely();
        }
        return out.get();
    }

    private String pickCamera(CameraManager mgr) throws Exception {
        String[] ids = mgr.getCameraIdList();
        for (String id : ids) {
            Integer facing = mgr.getCameraCharacteristics(id)
                    .get(CameraCharacteristics.LENS_FACING);
            if (facing != null && facing == CameraCharacteristics.LENS_FACING_BACK) {
                return id;
            }
        }
        return ids.length > 0 ? ids[0] : null;
    }

    private Size pickSize(CameraManager mgr, String id) throws Exception {
        CameraCharacteristics ch = mgr.getCameraCharacteristics(id);
        android.hardware.camera2.params.StreamConfigurationMap map =
                ch.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP);
        if (map == null) {
            return new Size(1280, 720);
        }
        Size[] sizes = map.getOutputSizes(ImageFormat.JPEG);
        if (sizes == null || sizes.length == 0) {
            return new Size(1280, 720);
        }
        Size best = sizes[0];
        for (Size s : sizes) {
            if (s.getWidth() <= 1600 && s.getWidth() > best.getWidth()) {
                best = s;
            }
        }
        if (best.getWidth() > 1600) {
            best = sizes[sizes.length - 1];
        }
        return best;
    }
}
