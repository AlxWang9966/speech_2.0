# AVIA - Audio-Visual Intelligence Assistant

🎯 **AVIA** is a comprehensive multi-language audio and visual content analysis platform built with Streamlit. It combines Azure AI Services with OpenAI's GPT-4 to provide intelligent transcription, analysis, and summarization capabilities across 7+ languages, transforming from a simple meeting assistant into a professional content intelligence solution.

## 🌟 Major Features & Capabilities

### 🎤 Multi-Language Audio Processing
- **7-Language Support**: English, Chinese (Simplified), Spanish, French, German, Japanese, Korean
- **Automatic Language Detection**: Smart detection and processing without manual language selection
- **Speaker Diarization**: Identifies different speakers in multi-participant audio
- **Azure Fast Transcription API**: Latest 2024-11-15 API for high-accuracy transcription
- **Multiple Audio Formats**: WAV, MP3, M4A support

### 🖼️ Advanced Image Analysis
- **Content Analysis**: Comprehensive image content understanding and description
- **OCR Capabilities**: Text extraction from images with multi-language support
- **Format Support**: JPG, JPEG, PNG formats
- **Context-Aware Analysis**: Image analysis adapts to detected audio language

### 🤖 Intelligent Content Summarization
- **Multi-Modal Integration**: Combines audio transcription and image analysis results
- **Language-Adaptive Processing**: Generates summaries in the detected content language
- **Custom Prompts**: User-defined analysis instructions for specialized content
- **Comprehensive Output**: Key insights, important information, and actionable summaries

### 🎨 Professional User Interface
- **Modern Design**: Gradient-based professional interface with AVIA branding
- **Responsive Layout**: Two-column design optimized for desktop and mobile
- **Progress Indicators**: Real-time processing status and completion feedback
- **Multi-Language UI**: Interface labels adapt to detected content language
- **Download Functionality**: Export transcriptions and summaries as text files

## 🚀 Major Updates & Transformations

### Complete Rebranding (Meeting Assistant → AVIA)
- ✅ **New Identity**: Transformed from "Meeting Assistant" to "Audio-Visual Intelligence Assistant (AVIA)"
- ✅ **Professional Branding**: Modern gradient headers, consistent color scheme, professional typography
- ✅ **Content Generalization**: Removed meeting-specific terminology for broader content applicability
- ✅ **Enhanced User Experience**: Improved visual hierarchy and intuitive navigation

### Technical Infrastructure Overhaul
- ✅ **Multi-Language Implementation**: Expanded from Chinese-only to 7-language support with auto-detection
- ✅ **API Modernization**: Upgraded to Azure Fast Transcription API 2024-11-15
- ✅ **Code Simplification**: Reduced speech transcription from complex fallback logic to clean 45-line implementation
- ✅ **Error Handling**: Robust error management and user feedback systems
- ✅ **Performance Optimization**: Streamlined processing pipeline for faster results

### Enhanced Analysis Capabilities
- ✅ **Generalized Prompts**: Updated from meeting-specific to universal content analysis across all languages
- ✅ **Context-Aware Processing**: Content analysis adapts based on detected language and content type
- ✅ **Multi-Modal Integration**: Seamless combination of audio and visual content analysis
- ✅ **Custom Analysis Options**: User-defined prompts for specialized content requirements

## 📁 File Structure

```
speech_2.0/
├── README.md                           # Project documentation
├── meeting_summary/                    # Main application directory
│   ├── meeting_sum.py                 # Main AVIA application
│   ├── llm_analysis.py               # OpenAI GPT-4 integration
│   ├── speech_fast_transcription.py  # Azure Speech service integration
│   └── .env                          # Azure API credentials (excluded from git)
└── speech_to_text/                    # Legacy speech processing modules
    ├── speech_ASR.py                  # Legacy ASR implementation
    └── text_queue.py                  # Text processing utilities
```

## 🛠️ Installation & Setup

### Prerequisites
- Python 3.8+
- Azure OpenAI Service account
- Azure Speech Service account
- Azure Translator Service account (optional, for enhanced language support)

### Installation Steps
1. **Clone Repository**:
   ```bash
   git clone https://github.com/AlxWang9966/speech_2.0.git
   cd speech_2.0/meeting_summary
   ```

2. **Install Dependencies**:
   ```bash
   pip install streamlit azure-cognitiveservices-speech openai python-dotenv
   ```

3. **Configure Environment**:
   Create `.env` file in the `meeting_summary` directory with your Azure credentials:
   ```env
   AZURE_OPENAI_API_KEY=your_openai_key
   AZURE_OPENAI_ENDPOINT=https://your-endpoint.openai.azure.com/
   AZURE_SPEECH_KEY=your_speech_key
   AZURE_SPEECH_REGION=your_region
   AZURE_TRANSLATOR_KEY=your_translator_key (optional)
   AZURE_TRANSLATOR_ENDPOINT=https://api.cognitive.microsofttranslator.com/
   AZURE_TRANSLATOR_REGION=your_region (optional)
   ```

4. **Run Application**:
   ```bash
   streamlit run meeting_sum.py
   ```

## 🔮 Potential Future Enhancements

### Copy-to-Clipboard Functionality
- **Challenge**: Multiple implementation attempts faced Streamlit's stateful nature limitations
- **Approaches Tried**: HTML/JavaScript integration, text areas, expandable code blocks
- **Future Solution**: Consider Streamlit components or alternative clipboard integration methods

### Advanced Features Roadmap
- **Real-Time Processing**: Live audio transcription and analysis during recording
- **Batch Processing**: Multiple file upload and processing capabilities
- **Export Options**: PDF reports, Word documents, structured data formats
- **Cloud Integration**: Direct integration with cloud storage services
- **Collaboration Features**: Sharing and collaborative analysis capabilities
- **Advanced Analytics**: Content trends, keyword extraction, sentiment analysis
- **API Endpoints**: RESTful API for integration with other applications

### Technical Improvements
- **Caching System**: Implement result caching for improved performance
- **Progressive Loading**: Chunked processing for large files
- **Enhanced Error Handling**: More granular error reporting and recovery
- **Accessibility Features**: Screen reader support, keyboard navigation
- **Mobile Optimization**: Enhanced mobile user experience
- **Internationalization**: Full UI translation for all supported languages

## 🔧 Technical Specifications

### Azure Services Integration
- **Azure OpenAI**: GPT-4o model for content analysis and summarization
- **Azure Speech**: Fast Transcription API 2024-11-15 with speaker diarization
- **Azure Translator**: Multi-language translation support (optional)

### Supported Languages & Locales
- **English**: en-US
- **Chinese (Simplified)**: zh-CN
- **Spanish**: es-ES
- **French**: fr-FR
- **German**: de-DE
- **Japanese**: ja-JP
- **Korean**: ko-KR

### Performance Characteristics
- **Audio Processing**: ~45-line implementation with automatic language detection
- **Multi-Modal Analysis**: Seamless integration of audio and visual content
- **Response Time**: Optimized for real-time user experience
- **Scalability**: Streamlit-based architecture suitable for personal and small team use

## 🎯 Success Metrics

### Completed Objectives
- ✅ **Multi-Language Support**: 7 languages with automatic detection
- ✅ **Professional UI**: Complete AVIA rebranding and modern interface
- ✅ **Content Generalization**: Universal applicability beyond meeting scenarios
- ✅ **Code Simplification**: Streamlined architecture while maintaining functionality
- ✅ **Error Resilience**: Robust error handling and user feedback

### User Experience Improvements
- ✅ **Intuitive Interface**: Professional gradient design with clear navigation
- ✅ **Progress Feedback**: Real-time processing status and completion indicators
- ✅ **Multi-Format Support**: Comprehensive audio and image format compatibility
- ✅ **Download Functionality**: Easy export of transcriptions and summaries
- ✅ **Responsive Design**: Optimized layout for various screen sizes

## 🚀 Quick Start

1. Navigate to the application directory and run:
   ```bash
   cd meeting_summary
   streamlit run meeting_sum.py
   ```

2. Open your browser to `http://localhost:8501`

3. Upload audio files or images and experience AVIA's intelligent analysis capabilities!

---

**AVIA** represents a significant evolution from a basic meeting assistant to a comprehensive audio-visual intelligence platform, demonstrating the power of combining multiple Azure AI services with modern web application design principles.
