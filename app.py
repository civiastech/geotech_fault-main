import streamlit as st
from PIL import Image as PILImage, ImageDraw
import os
import numpy as np
import onnxruntime
from feedback_data_onnx import feedback_data  # Your feedback dictionary
import pandas as pd
from io import BytesIO

st.title("🛠 Geotechnical Fault Detection (ONNX + Maintenance Feedback)")

uploaded_file = st.file_uploader("Upload an image...", type=["jpg", "jpeg", "png"])

ONNX_MODEL_PATH = 'best.onnx'

@st.cache_resource
def load_onnx_model(path):
    if os.path.exists(path):
        try:
            session = onnxruntime.InferenceSession(path, None)
            input_name = session.get_inputs()[0].name
            output_name = session.get_outputs()[0].name
            return session, input_name, output_name
        except Exception as e:
            st.error(f"Error loading ONNX model: {e}")
    else:
        st.error(f"ONNX model not found at {path}")
    return None, None, None

session, input_name, output_name = load_onnx_model(ONNX_MODEL_PATH)

CLASS_NAMES = [

    'Basket Corrosion Wall', 'Broken Basket', 'Bulging Face', 'Crack on Asphalt',
    'Deformation Wall', 'Expose foundation wall', 'Interface Opening', 'Long Crack GBA',
    'Long Crack Wall 1', 'Long Crack Wall 2', 'Mesh Crack Wall', 'Misalignment of wall',
    'Opening on GBA', 'Slope Deformation', 'Vegetation on Slope', 'Vegetation on Wall',
    'Vertical Crack GBA 1', 'Vertical Crack GBA 2', 'Vertical Crack Wall 1', 'Vertical Crack Wall 2'

]

if uploaded_file is not None:
    image = PILImage.open(uploaded_file).convert('RGB')
    st.image(image, caption="Uploaded Image", use_column_width=True)

    if session:
        st.write("🔍 Running inference...")

        img = np.array(image)
        img_resized = PILImage.fromarray(img).resize((640, 640))
        img_resized = np.array(img_resized)

        img_processed = img_resized[:, :, ::-1].transpose(2, 0, 1)
        img_processed = np.ascontiguousarray(img_processed).astype(np.float32) / 255.0
        img_processed = np.expand_dims(img_processed, 0)

        try:
            onnx_inputs = {input_name: img_processed}
            onnx_outputs = session.run([output_name], onnx_inputs)

            # Check output validity
            if not onnx_outputs or onnx_outputs[0] is None or len(onnx_outputs[0]) == 0:
                st.warning("⚠️ ONNX model returned empty output. No predictions made.")
                st.stop()

            try:
                predictions = onnx_outputs[0].transpose(0, 2, 1)[0]
            except Exception as e:
                st.error(f"❌ Failed to process ONNX output shape: {e}")
                st.stop()

            confidence_threshold = 0.25
            boxes = predictions[:, :4]
            confidences = np.max(predictions[:, 4:], axis=1)
            class_ids = np.argmax(predictions[:, 4:], axis=1)

            valid_detections = confidences > confidence_threshold
            boxes = boxes[valid_detections]
            class_ids = class_ids[valid_detections]
            confidences = confidences[valid_detections]

            if len(boxes) == 0:
                st.warning("⚠️ No valid detections above the confidence threshold.")
                st.stop()

            original_width, original_height = image.size
            img_size_model = 640

            # Convert from center_x, center_y, width, height to x_min, y_min, x_max, y_max and scale to original image size
            boxes[:, 0] = (boxes[:, 0] - boxes[:, 2] / 2) * (original_width / img_size_model)  # x_min
            boxes[:, 1] = (boxes[:, 1] - boxes[:, 3] / 2) * (original_height / img_size_model) # y_min
            boxes[:, 2] = (boxes[:, 0] + boxes[:, 2] * (original_width / img_size_model))      # x_max
            boxes[:, 3] = (boxes[:, 1] + boxes[:, 3] * (original_height / img_size_model))     # y_max

            draw = ImageDraw.Draw(image)
            colors = {}
            results_data = []

            for i in range(len(boxes)):
                box = boxes[i]
                class_id = int(class_ids[i])
                confidence = confidences[i]
                class_name = CLASS_NAMES[class_id]
                label = f"{class_name}: {confidence:.2f}"

                if class_id not in colors:
                    colors[class_id] = (np.random.randint(0, 255), np.random.randint(0, 255), np.random.randint(0, 255))
                color = colors[class_id]

                draw.rectangle([(box[0], box[1]), (box[2], box[3])], outline=color, width=2)
                draw.text((box[0], box[1]), label, fill=color)

                fault_key = class_name.lower().strip()
                feedback = feedback_data.get(fault_key)

                if feedback:
                    st.markdown(f"### 🧱 Fault: `{class_name}`")
                    st.markdown(f"📊 **Score**: `{feedback['score']}` — **Severity**: `{feedback['severity']}`")
                    st.markdown(f"🛠 **Recommendation**: {feedback['recommendation']}")
                    st.markdown(f"🔥 **Priority**: `{feedback['priority']}`")
                    st.markdown("---")
                else:
                    st.markdown(f"⚠️ No feedback found for `{class_name}`")

                # Bounding box metadata
                x_min = int(box[0])
                y_min = int(box[1])
                x_max = int(box[2])
                y_max = int(box[3])

                results_data.append({
                    "Image Filename": uploaded_file.name,
                    "Fault": class_name,
                    "Confidence": round(float(confidence), 2),
                    "Score": feedback['score'] if feedback else "N/A",
                    "Severity": feedback['severity'] if feedback else "N/A",
                    "Recommendation": feedback['recommendation'] if feedback else "N/A",
                    "Priority": feedback['priority'] if feedback else "N/A",
                    "X_min": x_min,
                    "Y_min": y_min,
                    "X_max": x_max,
                    "Y_max": y_max
                })

            st.image(image, caption="Detected Results", use_column_width=True)

            buf = BytesIO()
            image.save(buf, format="PNG")
            byte_im = buf.getvalue()

            st.download_button(
                label="📥 Download Annotated Image",
                data=byte_im,
                file_name="detected_faults.png",
                mime="image/png"
            )

            if results_data:
                df = pd.DataFrame(results_data)
                csv = df.to_csv(index=False).encode('utf-8')

                st.download_button(
                    label="📄 Download Detection + Feedback as CSV",
                    data=csv,
                    file_name="fault_feedback_results.csv",
                    mime="text/csv"
                )

        except Exception as e:
            st.error(f"❌ Error during ONNX inference or processing: {e}")

    else:
        st.warning("⚠️ Model session is not active.")

st.write("---")
st.write("🔗 Powered by YOLOv8 ONNX + Streamlit + Maintenance Intelligence")
